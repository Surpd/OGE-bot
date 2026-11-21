from app.persistence.part2_training import Part2Training


async def test_albums_resume_rotation_and_ownership(bank_pool):
    bank = Part2Training(bank_pool)
    for number in range(20, 26):
        issue = await bank.open(1, number)
        a = await bank.current(1, issue)
        assert a and a["card"]["number"] == number
        assert await bank.current(2, issue) is None
        assert await bank.append(2, issue, 1, 1, None, "wrong") == "stale"
        msg = number * 10
        album = f"album-{number}"
        assert await bank.append(1, issue, 1, msg, "старый кадр", "photo-a", album) == "saved"
        assert await bank.append(1, issue, 1, msg, "старый кадр", "photo-a", album) == "duplicate"
        reopened = Part2Training(bank_pool)
        assert (await reopened.current(1, issue, activate=True))["id"] == issue
        assert await reopened.append(1, issue, 1, msg + 1, None, "photo-b", album) == "photo_limit"
        assert await reopened.append(1, issue, 1, msg + 2, None, "photo-c") == "photo_limit"
        assert await reopened.append(1, issue, 1, msg + 3, "отдельный текст", None) == "saved"
        assert (
            await reopened.append(
                1, issue, 1, msg + 4, "новый кадр", "replacement", replace_photo=msg
            )
            == "saved"
        )
        work = await bank_pool.fetch(
            "SELECT body,photo FROM part2_work WHERE issue_id=$1 AND NOT superseded "
            "ORDER BY message_id",
            issue,
        )
        assert [tuple(r.values()) for r in work] == [
            ("отдельный текст", None),
            ("новый кадр", "replacement"),
        ]
        assert await reopened.skip(1, issue, 1)
        assert await reopened.open(1, number) != issue
        b = await bank.current(1)
        assert await bank.append(1, b["id"], 1, msg + 5, None, "late", album) == "stale"
        assert await bank.append(1, b["id"], 1, msg + 2, None, "photo-c") == "duplicate"
        assert b["subtype_id"] != a["subtype_id"]
        assert not await reopened.skip(1, issue, 1)


async def test_unseen_before_repeats_and_version_updates_keep_seen_identity(bank_pool):
    import asyncio

    bank = Part2Training(bank_pool)
    subtype = "OGE20-poly-factor"
    first, second = await asyncio.gather(bank.open(1, 20, subtype), bank.open(1, 20, subtype))
    a = await bank.current(1, first, activate=True)
    assert await bank.append(1, first, 1, 100, "Сохранённая работа", None) == "saved"
    b = await bank.current(1, second, activate=True)
    assert b["id"] != a["id"] and b["task_id"] != a["task_id"]
    assert await bank.skip(1, second, 1)
    assert await bank.open(1, 20, subtype, repeat="skipped") is None

    await bank_pool.execute(
        """INSERT INTO part2_versions(task_id,version,payload,digest,available)
           SELECT task_id,version+1,payload,digest,false
           FROM part2_versions WHERE task_id=$1 AND available""",
        b["task_id"],
    )
    await bank_pool.execute(
        "UPDATE part2_versions SET available=(version=$2) WHERE task_id=$1",
        b["task_id"],
        b["version"] + 1,
    )
    for _ in range(4):
        issue = await bank.open(1, 20, subtype)
        assert issue is not None and await bank.skip(1, issue, 1)
    assert await bank.open(1, 20, subtype) is None
    assert await bank.open(1, 20, subtype, repeat="errors") is None
    repeated = await bank.open(1, 20, subtype, repeat="skipped")
    assert repeated is not None
    rpt = await bank.current(1, repeated)
    assert rpt["task_id"] == b["task_id"]
    assert rpt["version"] == b["version"] + 1
    assert rpt["repeat_kind"] == "skipped"
    await bank_pool.execute(
        "UPDATE part2_issues SET issued_at=issued_at-interval '3 days', "
        "touched_at=touched_at-interval '3 days' WHERE owner=1"
    )
    draft = await Part2Training(bank_pool).current(1, first, activate=True)
    assert draft["draft"] and draft["card"] == a["card"]
    assert (await bank.current(1))["id"] == first
    assert (await bank_pool.fetchval("SELECT count(*) FROM part2_grades")) == 0

    # The old result qualifies for explicit error practice, and remains in history.
    await bank_pool.execute(
        """INSERT INTO part2_grades(issue_id,revision,model,prompt_version,rubric_version,
               status,score,reserved_usd,cost_usd)
           VALUES($1,1,'synthetic','test',1,'graded',1,0,0)""",
        first,
    )
    assert await bank.finish(1, first)
    alternative = await bank.open(1, 20, subtype, repeat="errors")
    assert alternative and alternative != first
    assert (await bank.current(1, alternative))["task_id"] == a["task_id"]
    assert (
        await bank_pool.fetchval("SELECT score FROM part2_grades WHERE issue_id=$1", first)
    ) == 1


async def test_subtype_and_number_sequences_match_independent_model(bank_pool):
    import json

    from app.persistence.part2_bank import ATLAS
    from scripts.part2_rotation_audit import sequence

    cards = list(map(json.loads, (ATLAS / "tasks.jsonl").read_text().splitlines()))
    catalog = json.loads((ATLAS / "rotation.json").read_text())
    for subtype, groups in catalog.items():
        number = int(subtype[3:5])
        listed = [task for g in groups for task in g["cards"]]
        assert sorted(listed) == sorted(c["task_id"] for c in cards if c["subtype_id"] == subtype)
        # Separate learners keep the six-card examples independently reproducible.
        owner = await bank_pool.fetchval("SELECT coalesce(max(telegram_user_id),0)+1 FROM users")
        await bank_pool.execute("INSERT INTO users(telegram_user_id) VALUES($1)", owner)
        expected = sequence(cards, catalog, number, [subtype] * len(listed), owner)
        for task in expected:
            repo = Part2Training(bank_pool)
            issue = await repo.open(owner, number, subtype)
            row = await repo.current(owner, issue)
            assert row["task_id"] == task
            assert await repo.skip(owner, issue, 1)
        assert await repo.open(owner, number, subtype) is None

    repo = Part2Training(bank_pool)
    for number in range(20, 26):
        subtypes = [s for s in catalog if s.startswith(f"OGE{number}-")]
        requests = [None] * 15 + [subtypes[i % len(subtypes)] for i in range(15)]
        expected = sequence(cards, catalog, number, requests)
        assert len(set(expected)) == 30
        for subtype, task in zip(requests, expected, strict=True):
            issue = await repo.open(1, number, subtype)
            assert (await repo.current(1, issue))["task_id"] == task
            assert await repo.skip(1, issue, 1)

import asyncio

from app.persistence.part2_training import Part2Training


async def test_albums_resume_rotation_and_ownership(bank_pool):
    bank = Part2Training(bank_pool)
    for number in range(20, 26):
        result = await asyncio.gather(bank.open(1, number), bank.open(1, number))
        assert result[0] == result[1]
        issue = result[0]
        a = await bank.current(1, issue)
        assert a and a["card"]["number"] == number
        assert await bank.current(2, issue) is None
        assert await bank.append(2, issue, 1, 1, None, "wrong") == "stale"
        msg = number * 10
        album = f"album-{number}"
        assert await bank.append(1, issue, 1, msg, "старый кадр", "photo-a", album) == "saved"
        assert await bank.append(1, issue, 1, msg, "старый кадр", "photo-a", album) == "duplicate"
        reopened = Part2Training(bank_pool)
        assert await reopened.open(1, number) == issue
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
        assert await reopened.open(1, number, replace=issue) != issue
        b = await bank.current(1)
        assert await bank.append(1, b["id"], 1, msg + 5, None, "late", album) == "stale"
        assert await bank.append(1, b["id"], 1, msg + 2, None, "photo-c") == "duplicate"
        assert b["subtype_id"] != a["subtype_id"]
        assert await reopened.open(1, number, replace=issue) is None

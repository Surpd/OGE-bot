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
        assert not await bank.append(2, issue, 1, 1, None, "wrong", 4)
        assert await bank.append(1, issue, 1, 5, "step 1", "photo-a", 2, f"album-{number}")
        assert not await bank.append(1, issue, 1, 5, "step 1", "photo-a", 2, f"album-{number}")
        reopened = Part2Training(bank_pool)
        assert await reopened.open(1, number) == issue
        assert await reopened.append(1, issue, 1, 6, None, "photo-b", 2, f"album-{number}")
        assert not await reopened.append(1, issue, 1, 7, None, "photo-c", 2)
        assert await reopened.open(1, number, replace=issue) != issue
        b = await bank.current(1)
        assert not await bank.append(1, b["id"], 1, 9, None, "late", 2, f"album-{number}")
        assert b["subtype_id"] != a["subtype_id"]
        assert await reopened.open(1, number, replace=issue) is None

from supernote.client.file import FileClient


async def test_capacity_query(file_client: FileClient) -> None:
    # 1. Initial State
    # Capacity should be empty (or near empty if other tests ran, but fixture creates fresh user usually)
    # Actually conftest usually creates a fresh DB per session but maybe same user?
    # Let's assume fresh for now or check relative changes.

    cap = await file_client.get_capacity_web()
    initial_used = cap.used_capacity
    # Default quota is 10GB
    assert cap.total_capacity == 10 * 1024 * 1024 * 1024

    # 2. Upload a file
    content = b"x" * 1024  # 1KB
    await file_client.upload_content("/capacity_test.txt", content, equipment_no="test")

    # 3. Check Capacity Updated
    cap_after = await file_client.get_capacity_web()
    assert cap_after.used_capacity == initial_used + 1024
    assert cap_after.total_capacity == cap.total_capacity

    # Verify device API works the same
    device_cap = await file_client.get_capacity()
    assert device_cap.used == cap_after.used_capacity
    assert device_cap.allocation_vo
    assert device_cap.allocation_vo.allocated == cap_after.total_capacity

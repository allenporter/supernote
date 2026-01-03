from supernote.client.device import DeviceClient


async def test_capacity_query_device(device_client: DeviceClient) -> None:
    # 1. Initial State
    # Note: get_capacity is the Device API method
    cap = await device_client.get_capacity()
    initial_used = cap.used
    # Default quota is 10GB
    assert cap.allocation_vo
    assert cap.allocation_vo.allocated == 10 * 1024 * 1024 * 1024

    # 2. Upload a file
    content = b"y" * 2048  # 2KB
    await device_client.upload_content("/capacity_test_device.txt", content, equipment_no="test")

    # 3. Check Capacity Updated
    cap_after = await device_client.get_capacity()
    assert cap_after.used == initial_used + 2048
    assert cap_after.allocation_vo
    assert cap_after.allocation_vo.allocated == cap.allocation_vo.allocated

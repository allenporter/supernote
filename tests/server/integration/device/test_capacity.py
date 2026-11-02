from supernote.client.device import DeviceClient


async def test_capacity_query_device(device_client: DeviceClient) -> None:
    cap = await device_client.get_capacity()
    initial_used = cap.used
    assert cap.allocation_vo
    assert cap.allocation_vo.allocated > initial_used

    content = b"y" * 2048
    await device_client.upload_content(
        "/capacity_test_device.txt", content, equipment_no="test"
    )

    cap_after = await device_client.get_capacity()
    assert cap_after.used == initial_used + 2048
    assert cap_after.allocation_vo
    assert cap_after.allocation_vo.allocated > cap_after.used

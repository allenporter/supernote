from supernote.client.web import WebClient


async def test_capacity_query_web(
    web_client: WebClient,
) -> None:
    cap = await web_client.get_capacity_web()
    initial_used = cap.used_capacity
    assert cap.total_capacity > initial_used

    content = b"x" * 1024
    await web_client.upload_file(
        parent_id=0, name="capacity_test_web.txt", content=content
    )

    cap_after = await web_client.get_capacity_web()
    assert cap_after.used_capacity == initial_used + 1024
    assert cap_after.total_capacity > cap_after.used_capacity

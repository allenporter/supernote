from supernote.client.web import WebClient


async def test_capacity_query_web(
    web_client: WebClient,
) -> None:
    # 1. Initial State
    cap = await web_client.get_capacity_web()
    initial_used = cap.used_capacity
    # Default quota is 10GB
    assert cap.total_capacity == 10 * 1024 * 1024 * 1024

    # 2. Upload a file via Web API
    content = b"x" * 1024  # 1KB
    await web_client.upload_file(
        parent_id=0, name="capacity_test_web.txt", content=content
    )

    # 3. Check Capacity Updated
    cap_after = await web_client.get_capacity_web()
    assert cap_after.used_capacity == initial_used + 1024
    assert cap_after.total_capacity == cap.total_capacity

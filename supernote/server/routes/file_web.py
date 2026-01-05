import logging
import urllib.parse
import uuid
from pathlib import Path
from typing import TypeVar

from aiohttp import web

from supernote.models.base import (
    BaseResponse,
    BooleanEnum,
    create_error_response,
)
from supernote.models.file_common import FileUploadApplyLocalVO
from supernote.models.file_web import (
    CapacityVO,
    EntriesVO,
    FileDeleteDTO,
    FileLabelSearchDTO,
    FileLabelSearchVO,
    FileListQueryDTO,
    FileListQueryVO,
    FileMoveAndCopyDTO,
    FilePathQueryDTO,
    FilePathQueryVO,
    FileReNameDTO,
    FileSortOrder,
    FileSortSequence,
    FileUploadApplyDTO,
    FileUploadFinishDTO,
    FolderAddDTO,
    FolderListQueryDTO,
    FolderListQueryVO,
    FolderVO,
    RecycleFileDTO,
    RecycleFileListDTO,
    RecycleFileListVO,
    RecycleFileVO,
    UserFileVO,
)
from supernote.server.constants import CATEGORY_CONTAINERS
from supernote.server.services.file import (
    FileEntity,
    FileService,
    FileServiceException,
    InvalidPathException,
    RecycleEntity,
)

logger = logging.getLogger(__name__)
routes = web.RouteTableDef()

_T = TypeVar("_T", bound=(FileEntity | RecycleEntity))


def _sort_and_page(
    items: list[_T],
    sequence: FileSortSequence,
    order: FileSortOrder,
    page_no: int,
    page_size: int,
) -> tuple[list[_T], int]:
    """Sort and paginate a list of items.

    Returns:
        tuple[list[_T], int]: the page of items and the total number of items.
    """
    # Sorting
    reverse = sequence.lower() == FileSortSequence.DESC
    if order == FileSortOrder.FILENAME:
        items.sort(key=lambda x: x.name, reverse=reverse)
    elif order == FileSortOrder.SIZE:
        items.sort(key=lambda x: x.size, reverse=reverse)
    else:  # time
        items.sort(key=lambda x: x.sort_time, reverse=reverse)

    # Pagination
    total = len(items)
    start = (page_no - 1) * page_size
    end = start + page_size
    page_items = items[start:end]
    return page_items, total


def _flatten_path(path: str) -> str:
    """Flatten paths for items inside category containers (e.g., NOTE/Note -> Note)."""

    path_parts = path.strip("/").split("/")
    if len(path_parts) >= 2 and path_parts[0] in CATEGORY_CONTAINERS:
        # Convert NOTE/Note/Sub -> Note/Sub
        return "/".join(path_parts[1:])
    return path


@routes.post("/api/file/capacity/query")
async def handle_capacity_query_cloud(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/capacity/query
    # Purpose: Get storage capacity usage (Cloud).
    # Response: CapacityVO

    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    # TODO: Implement quota properly
    used = await file_service.get_storage_usage(user_email)
    return web.json_response(
        CapacityVO(
            used_capacity=used,
            total_capacity=1024 * 1024 * 1024 * 10,  # 10GB total
        ).to_dict()
    )


@routes.post("/api/file/recycle/list/query")
async def handle_recycle_list(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/recycle/list/query
    # Purpose: List files in recycle bin.

    req_data = RecycleFileListDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    recycle_files = await file_service.list_recycle(
        user_email,
    )

    page_items, total = _sort_and_page(
        recycle_files,
        req_data.sequence,
        req_data.order,
        req_data.page_no,
        req_data.page_size,
    )

    result_items = []
    for item in page_items:
        result_items.append(
            RecycleFileVO(
                # Recycle ID, not Original File ID? Client usually wants ID to action on.
                file_id=str(item.id),
                is_folder="Y" if item.is_folder else "N",
                file_name=item.name,
                size=item.size,
                update_time=str(item.delete_time),
            )
        )

    response = RecycleFileListVO(total=total, recycle_file_vo_list=result_items)
    return web.json_response(response.to_dict())


@routes.post("/api/file/recycle/delete")
async def handle_recycle_delete(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/recycle/delete
    # Purpose: Permanently delete items from recycle bin.
    # Response: BaseVO

    req_data = RecycleFileDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    response = await file_service.delete_from_recycle(user_email, req_data.id_list)
    return web.json_response(response.to_dict())


@routes.post("/api/file/recycle/revert")
async def handle_recycle_revert(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/recycle/revert
    # Purpose: Restore items from recycle bin.
    # Response: BaseVO

    req_data = RecycleFileDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    response = await file_service.revert_from_recycle(user_email, req_data.id_list)
    return web.json_response(response.to_dict())


@routes.post("/api/file/recycle/clear")
async def handle_recycle_clear(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/recycle/clear
    # Purpose: Empty the recycle bin.

    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    response = await file_service.clear_recycle(user_email)
    return web.json_response(response.to_dict())


@routes.post("/api/file/path/query")
async def handle_path_query(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/path/query
    # Purpose: Resolve file path and ID path.
    # Response: FilePathQueryVO

    req_data = FilePathQueryDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    path_info = await file_service.get_path_info(user_email, req_data.id, flatten=True)
    response = FilePathQueryVO(path=path_info.path, id_path=path_info.id_path)
    return web.json_response(response.to_dict())


@routes.post("/api/file/list/query")
async def handle_file_list_query(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/list/query
    # Purpose: Query files in a directory.
    # Response: FileListQueryVO

    req_data = FileListQueryDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    file_entities = await file_service.query_file_list(
        user_email,
        req_data.directory_id,
    )

    page_items, total = _sort_and_page(
        file_entities,
        req_data.sequence,
        req_data.order,
        req_data.page_no,
        req_data.page_size,
    )

    user_file_vos: list[UserFileVO] = []
    for entity in page_items:
        user_file_vos.append(
            UserFileVO(
                id=str(entity.id),
                directory_id=str(entity.parent_id),
                file_name=entity.name,
                size=entity.size,
                md5=entity.md5,
                inner_name=entity.md5,  # Using md5 as inner_name compatible
                is_folder=BooleanEnum.YES if entity.is_folder else BooleanEnum.NO,
                create_time=entity.create_time,
                update_time=entity.update_time,
            )
        )

    pages = max(1, (total + req_data.page_size - 1) // req_data.page_size)

    response = FileListQueryVO(
        total=total,
        pages=pages,
        page_num=req_data.page_no,
        page_size=req_data.page_size,
        user_file_vo_list=user_file_vos,
    )
    return web.json_response(response.to_dict())


@routes.post("/api/file/label/list/search")
async def handle_file_search(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/label/list/search
    # Purpose: Search for files by keyword.
    # Response: FileSearchResponse

    req_data = FileLabelSearchDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    file_entities = await file_service.search_files(
        user_email, req_data.keyword, flatten=True
    )

    entries_vos: list[EntriesVO] = []
    for entity in file_entities:
        # Web API expects flattened paths for system directories
        path_display = _flatten_path(entity.full_path)
        parent_path = str(Path(path_display).parent)
        if parent_path == ".":
            parent_path = ""

        entries_vos.append(
            EntriesVO(
                tag="folder" if entity.is_folder else "file",
                id=str(entity.id),
                name=entity.name,
                path_display=path_display,
                parent_path=parent_path,
                size=entity.size,
                last_update_time=entity.update_time,
                content_hash=entity.md5 or "",
                is_downloadable=True,
            )
        )

    response = FileLabelSearchVO(entries=entries_vos)
    return web.json_response(response.to_dict())


@routes.post("/api/file/folder/add")
async def handle_folder_add(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/folder/add
    # Purpose: Create a new folder (Web).
    # Response: FolderVO

    req_data = FolderAddDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    try:
        new_dir = await file_service.create_directory_by_id(
            user_email, req_data.directory_id, req_data.file_name
        )
    except InvalidPathException as e:
        return web.json_response(create_error_response(str(e)).to_dict(), status=400)
    except FileServiceException as e:
        return web.json_response(create_error_response(str(e)).to_dict(), status=500)

    response = FolderVO(
        id=str(new_dir.id),
        directory_id=str(new_dir.parent_id),
        file_name=new_dir.name,
        # TODO: What is the expected behavior when targeting an existing non-empty directory?
        empty=BooleanEnum.YES,  # Newly created is empty
    )
    return web.json_response(response.to_dict())


@routes.post("/api/file/folder/list/query")
async def handle_folder_list_query(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/folder/list/query
    # Purpose: Query details for a list of folders.
    # Response: FolderListQueryVO

    req_data = FolderListQueryDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    folder_details = await file_service.get_folders_by_ids(
        user_email, req_data.directory_id, req_data.id_list, flatten=True
    )

    folder_vos: list[FolderVO] = []
    for detail in folder_details:
        folder_vos.append(
            FolderVO(
                id=str(detail.entity.id),
                directory_id=str(detail.entity.parent_id),
                file_name=detail.entity.name,
                empty=BooleanEnum.NO if detail.has_subfolders else BooleanEnum.YES,
            )
        )

    response = FolderListQueryVO(folder_vo_list=folder_vos)
    return web.json_response(response.to_dict())


@routes.post("/api/file/move")
async def handle_file_move_web(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/move
    # Purpose: Move files/folders (Web).
    # Response: BaseResponse

    req_data = FileMoveAndCopyDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    response = await file_service.move_items(
        user_email, req_data.id_list, req_data.directory_id, req_data.go_directory_id
    )
    return web.json_response(response.to_dict())


@routes.post("/api/file/copy")
async def handle_file_copy_web(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/copy
    # Purpose: Copy files/folders (Web).
    # Response: BaseResponse

    req_data = FileMoveAndCopyDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    response = await file_service.copy_items(
        user_email, req_data.id_list, req_data.directory_id, req_data.go_directory_id
    )
    return web.json_response(response.to_dict())


@routes.post("/api/file/rename")
async def handle_file_rename_web(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/rename
    # Purpose: Rename file/folder (Web).
    # Response: BaseResponse

    req_data = FileReNameDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    response = await file_service.rename_item(
        user_email, req_data.id, req_data.new_name
    )
    return web.json_response(response.to_dict())


@routes.post("/api/file/delete")
async def handle_file_delete(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/delete
    # Purpose: Delete file/folder (Web).
    # Response: BaseResponse

    req_data = FileDeleteDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    try:
        response = await file_service.delete_items(
            user_email, req_data.id_list, req_data.directory_id
        )
    except InvalidPathException as err:
        return web.json_response(create_error_response(str(err)).to_dict(), status=400)
    except FileServiceException as err:
        return web.json_response(create_error_response(str(err)).to_dict(), status=500)
    return web.json_response(response.to_dict())


@routes.post("/api/file/upload/apply")
async def handle_file_upload_apply(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/upload/apply
    # Purpose: Request upload (Web).
    # Response: FileUploadApplyLocalVO

    req_data = FileUploadApplyDTO.from_dict(await request.json())
    url_signer = request.app["url_signer"]

    # Generate inner_name
    ext = "".join(Path(req_data.file_name).suffixes)
    inner_name = f"{uuid.uuid4()}{ext}"

    # Sign URL
    encoded_name = urllib.parse.quote(inner_name)
    path_to_sign = f"/api/oss/upload?object_name={encoded_name}"
    signed_path = url_signer.sign(path_to_sign, user=request["user"])
    full_url = f"{request.scheme}://{request.host}{signed_path}"

    return web.json_response(
        FileUploadApplyLocalVO(
            full_upload_url=full_url,
            inner_name=inner_name,
        ).to_dict()
    )


@routes.post("/api/file/upload/finish")
async def handle_file_upload_finish(request: web.Request) -> web.Response:
    # Endpoint: POST /api/file/upload/finish
    # Purpose: Complete upload (Web).
    # Response: BaseResponse

    req_data = FileUploadFinishDTO.from_dict(await request.json())
    user_email = request["user"]
    file_service: FileService = request.app["file_service"]

    try:
        await file_service.upload_finish_web(
            user=user_email,
            directory_id=req_data.directory_id,
            file_name=req_data.file_name,
            md5=req_data.md5,
            inner_name=req_data.inner_name,
        )
    except InvalidPathException as e:
        return web.json_response(create_error_response(str(e)).to_dict(), status=400)
    except FileServiceException as e:
        return web.json_response(create_error_response(str(e)).to_dict(), status=500)

    return web.json_response(BaseResponse(success=True).to_dict())

# API Data Model for Supernote (Private) Cloud Server.

This module describes the data models used by the Supernote Private Cloud API. These
models serve as a reference for both client and server implementations looking
to interoperate with the Supernote Private Cloud API. While this may also work
with the Supernote hosted cloud public API, it is not intended to be used there
to not put load on Supernote API servers.

We've described the sections of the system in terms of "Controllers" and shared
responsibilities to have a common mental model for how the system works.

## 1. Authentication & User Management

### Login & Logout

The LoginController is the main controller for handling user login and logout requests.

*   `POST /api/official/user/account/login/new`: Account Login
*   `POST /api/official/user/account/login/equipment`: Device Token Login
*   `POST /api/user/sms/login`: SMS Login
*   `POST /api/user/logout`: Logout
*   `POST /api/user/query/loginRecord`: Query Login History
*   `POST /api/user/query/token`: Validate/Query Token
*   `POST /api/official/user/query/random/code`: Get Random Code (for login crypto)

### User Profile

The UserController is the main controller for handling user profile requests.

*   `POST /api/user/check/exists`: Check User Exists
*   `POST /api/official/user/check/exists/server`: Check User Exists (Server Aware)
*   `POST /api/user/query`: Query Current User (Internal)
*   `POST /api/user/query/info`: Query User Info
*   `POST /api/user/update`: Update User Info
*   `POST /api/user/update/name`: Update Nickname
*   `POST /api/user/query/all`: Query All Users
*   `PUT /api/user/freeze`: Freeze/Unfreeze Account
*   `POST /api/user/query/one`: Query Single User
*   `GET /api/user/query/user/{userId}`: Query User by ID

### Registration

The UserRegisterController is the main controller for handling user registration requests.

*   `POST /api/user/register`: User Registration
*   `POST /api/user/account/clear`: Delete Account

### Password & Security

The PasswordController is the main controller for handling password and security requests.

*   `POST /api/official/user/retrieve/password`: Retrieve Password
*   `PUT /api/user/password`: Change Password

### Validation Codes

The ValidCodeController is the main controller for handling validation code requests.

*   `POST /api/user/mail/validcode`: Send Email Validation Code
*   `POST /api/user/check/validcode`: Verify Code
*   `GET /api/base/pic/code`: Get Graphic Verification Code

### Account Settings

The AccountController is the main controller for handling account settings requests.

*   `PUT /api/user/email`: Update Email Address

---

## 2. File Management (Web & General)

### Web File Operations

The FileLocalWebController is the main controller for handling web file operations requests.

*   `POST /api/file/list/query`: List Files & Folders
*   `POST /api/file/folder/list/query`: List Folders Only
*   `POST /api/file/capacity/query`: Query Storage Usage
*   `POST /api/file/delete`: Delete File/Folder
*   `POST /api/file/folder/add`: Create New Folder
*   `POST /api/file/move`: Move File/Folder
*   `POST /api/file/copy`: Copy File/Folder
*   `POST /api/file/rename`: Rename File/Folder
*   `POST /api/file/list/search`: Search Files
*   `POST /api/file/path/query`: Get File Path Info
*   **Recycle Bin:**
    *   `POST /api/file/recycle/list/query`: List Recycle Bin
    *   `POST /api/file/recycle/clear`: Empty Recycle Bin
    *   `POST /api/file/recycle/delete`: Permanently Delete
    *   `POST /api/file/recycle/revert`: Restore File
*   **Upload/Download:**
    *   `POST /api/file/download/url`: Get Download URL
    *   `POST /api/file/upload/apply`: Request Upload
    *   `POST /api/file/upload/finish`: Complete Upload

### Basic File Ops

The FileController is the main controller for handling basic file operations requests.

*   `POST /api/file/add/folder/file/deleteApi`: Add Folder/File (Desktop)
*   `POST /api/file/2/files/query/deleteApi`: Query File (Dropbox style)
*   `POST /api/file/2/files`: Query File by Path

### File Search

The FileSearchController is the main controller for handling file search requests.  

*   `POST /api/file/label/list/search`: Search by Label/Name

### Terminal Specific

The TerminalFileUploadController is the main controller for handling terminal file upload requests.

*   `POST /api/file/terminal/upload/apply`: Terminal Upload Request
*   `POST /api/file/terminal/upload/finish`: Terminal Upload Complete

---

## 3. Cloud/NAS Synchronization (Device API)

The FileLocalController is the main controller for handling cloud/nas synchronization requests.

### Sync Handshake

The FileLocalController is the main controller for handling cloud/nas synchronization requests.

*   `POST /api/file/2/files/synchronous/start`: Start Sync Session
*   `POST /api/file/2/files/synchronous/end`: End Sync Session

### Device File Operations

The FileLocalController is the main controller for handling cloud/nas synchronization requests.

*   `POST /api/file/2/files/create_folder_v2`: Create Folder
*   `POST /api/file/2/files/list_folder`: List Folder (V2)
*   `POST /api/file/3/files/list_folder_v3`: List Folder (V3)
*   `POST /api/file/3/files/delete_folder_v3`: Delete Folder/File
*   `POST /api/file/3/files/query_v3`: Query File
*   `POST /api/file/3/files/query/by/path_v3`: Query File by Path
*   `POST /api/file/3/files/move_v3`: Move File
*   `POST /api/file/3/files/copy_v3`: Copy File
*   `POST /api/file/2/users/get_space_usage`: Check Capacity

### Device Upload/Download

The FileLocalController is the main controller for handling cloud/nas synchronization requests.

*   `POST /api/file/3/files/upload/apply`: Upload Request
*   `POST /api/file/2/files/upload/finish`: Upload Finish
*   `POST /api/file/3/files/download_v3`: Download Request

### File Conversion

The FileLocalController is the main controller for handling cloud/nas synchronization requests.

*   `POST /api/file/note/to/pdf`: Convert Note to PDF
*   `POST /api/file/note/to/png`: Convert Note to PNG
*   `POST /api/file/pdfwithmark/to/pdf`: Convert PDF with Mark to PDF

### Connectivity

The FileLocalController is the main controller for handling cloud/nas synchronization requests.

*   `GET /api/file/query/server`: Ping Server

---

## 4. Advanced Features

### Sharing

The ShareController is the main controller for handling sharing requests.

*   `POST /api/file/share/record/add`: Create Share Record

### Scheduling & Calendar

The ScheduleController is the main controller for handling scheduling and calendar requests.

*   **Groups:**
    *   `POST /api/file/schedule/group`: Add Group
    *   `PUT /api/file/schedule/group`: Update Group
    *   `DELETE /api/file/schedule/group/{taskListId}`: Delete Group
    *   `POST /api/file/schedule/group/clear`: Clear Group
    *   `GET /api/file/schedule/group/{taskListId}`: Get Group
    *   `POST /api/file/schedule/group/all`: Get All Groups
*   **Tasks:**
    *   `POST /api/file/schedule/task`: Add Task
    *   `PUT /api/file/schedule/task`: Update Task
    *   `PUT /api/file/schedule/task/list`: Batch Update Tasks
    *   `DELETE /api/file/schedule/task/{taskId}`: Delete Task
    *   `GET /api/file/schedule/task/{taskId}`: Get Task
    *   `POST /api/file/schedule/task/all`: Get All Tasks
*   **Sorting:**
    *   `POST /api/file/schedule/sort`: Add Sort
    *   `PUT /api/file/schedule/sort`: Update Sort
    *   `DELETE /api/file/schedule/sort/{taskListId}`: Delete Sort
    *   `POST /api/file/query/schedule/sort`: Get Sort

### Summaries & Tags

The SummaryController is the main controller for handling summaries and tags requests.

*   `POST /api/file/add/summary/tag`: Add Tag
*   `PUT /api/file/update/summary/tag`: Update Tag
*   `DELETE /api/file/delete/summary/tag`: Delete Tag
*   `GET /api/file/query/summary/tag`: Query Tags
*   `POST /api/file/add/summary`: Add Summary
*   `PUT /api/file/update/summary`: Update Summary
*   `DELETE /api/file/delete/summary`: Delete Summary
*   `POST /api/file/query/summary`: Query Summaries
*   `POST /api/file/download/summary`: Download Summary
*   `POST /api/file/upload/apply/summary`: Upload Summary

---

## 5. System & Infrastructure

### Equipment Management

The EquipmentController is the main controller for handling equipment management requests.

*   `POST /api/terminal/user/activateEquipment`: Activate Device
*   `POST /api/terminal/user/bindEquipment`: Bind Device
*   `POST /api/terminal/equipment/unlink`: Unbind Device
*   `POST /api/equipment/bind/status`: Check Bind Status
*   `POST /api/equipment/query/user/equipment/deleteApi`: Query Equipment List
*   `POST /api/equipment/query/by/equipmentno`: Query by Serial No
*   `GET /api/equipment/query/by/{userId}`: Query by User ID

### OSS (Object Storage)

The OssLocalController is the main controller for handling object storage requests.

*   `POST /api/oss/generate/upload/url`: Get Upload URL
*   `POST /api/oss/upload`: Upload File
*   `POST /api/oss/upload/part`: Multipart Upload
*   `POST /api/oss/generate/download/url`: Get Download URL
*   `GET /api/oss/download`: Download File

### Configuration & Logs

Other misc controllers (EmailServerController, SensitiveOperationController, DictionaryController)

*   `POST /api/save/email/config`: Save Email Config
*   `GET /api/query/email/config`: Query Email Config
*   `POST /api/user/query/sensitive/record`: Query Sensitive Op Records
*   `POST /api/system/base/dictionary/deleteApi`: Query Dictionary

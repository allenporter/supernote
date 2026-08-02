"""Tests for Socket.IO data models and serialization."""

import json

from supernote.models.socket import (
    SocketHandshakeParams,
    SocketIoAction,
    SocketIoMessageTemplate,
    SocketIoMessageType,
    SocketMessageData,
)


def test_socket_handshake_params_serialization() -> None:
    params = SocketHandshakeParams(
        token="test-jwt-token",
        type="file",
        random="123456",
        sign="abcdef123456",
    )

    data_dict = params.to_dict()
    assert data_dict == {
        "token": "test-jwt-token",
        "type": "file",
        "random": "123456",
        "sign": "abcdef123456",
    }

    restored = SocketHandshakeParams.from_dict(data_dict)
    assert restored.token == "test-jwt-token"
    assert restored.type == "file"
    assert restored.random == "123456"
    assert restored.sign == "abcdef123456"


def test_socket_io_message_template_serialization() -> None:
    template = SocketIoMessageTemplate(
        message_type=SocketIoAction.ADDFOLDER,
        equipment_no="SN123456",
        file_type="folder",
        id=10,
        original_name="Old Folder",
        new_name="New Folder",
        directory_id=1,
        go_directory_id=2,
        timestamp=1700000000000,
    )

    d = template.to_dict()
    assert d == {
        "messageType": "ADDFOLDER",
        "equipmentNo": "SN123456",
        "fileType": "folder",
        "id": 10,
        "newId": None,
        "originalName": "Old Folder",
        "newName": "New Folder",
        "md5": None,
        "size": None,
        "directoryId": 1,
        "goDirectoryId": 2,
        "originalPath": None,
        "newPath": None,
        "timestamp": 1700000000000,
    }

    # JSON roundtrip
    json_str = json.dumps(d)
    deserialized = SocketIoMessageTemplate.from_dict(json.loads(json_str))
    assert deserialized.message_type == SocketIoAction.ADDFOLDER
    assert deserialized.equipment_no == "SN123456"
    assert deserialized.new_name == "New Folder"


def test_socket_message_data_envelope_serialization() -> None:
    template1 = SocketIoMessageTemplate(
        message_type=SocketIoAction.MOVEFILE,
        equipment_no="SN999999",
        file_type="note",
        id=42,
        original_path="/Documents/Note.note",
        new_path="/Archive/Note.note",
    )

    envelope = SocketMessageData(
        code="0",
        msg="success",
        timestamp=1700000005000,
        msg_type=SocketIoMessageType.FILE_SYN,
        data=[template1],
    )

    d = envelope.to_dict()
    assert d["code"] == "0"
    assert d["msg"] == "success"
    assert d["msgType"] == "FILE-SYN"
    assert len(d["data"]) == 1
    assert d["data"][0]["messageType"] == "MOVEFILE"
    assert d["data"][0]["originalPath"] == "/Documents/Note.note"

    restored = SocketMessageData.from_dict(d)
    assert restored.code == "0"
    assert restored.msg_type == SocketIoMessageType.FILE_SYN
    assert len(restored.data) == 1
    assert restored.data[0].original_path == "/Documents/Note.note"

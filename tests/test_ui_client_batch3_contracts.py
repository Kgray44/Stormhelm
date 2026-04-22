from __future__ import annotations

from PySide6 import QtCore, QtNetwork

from stormhelm.ui.client import CoreApiClient


class _FakeReply:
    def __init__(self, *, error: QtNetwork.QNetworkReply.NetworkError, error_string: str, body: bytes = b"") -> None:
        self._error = error
        self._error_string = error_string
        self._body = body
        self.deleted = False

    def error(self) -> QtNetwork.QNetworkReply.NetworkError:
        return self._error

    def errorString(self) -> str:
        return self._error_string

    def readAll(self) -> QtCore.QByteArray:
        return QtCore.QByteArray(self._body)

    def deleteLater(self) -> None:
        self.deleted = True


def test_core_api_client_prefers_backend_detail_for_http_failures() -> None:
    client = CoreApiClient("http://stormhelm.test")
    errors: list[tuple[str, str]] = []
    client.error_occurred.connect(lambda purpose, error: errors.append((purpose, error)))

    reply = _FakeReply(
        error=QtNetwork.QNetworkReply.NetworkError.ContentNotFoundError,
        error_string="Error transferring https://stormhelm.test/jobs/job-42/cancel - server replied: Not Found",
        body=b'{"detail":"Unknown job id."}',
    )

    client._handle_reply(reply, lambda payload: errors.append(("callback", str(payload))), "/jobs/job-42/cancel")

    assert errors == [("/jobs/job-42/cancel", "Unknown job id.")]
    assert reply.deleted is True


def test_core_api_client_falls_back_to_transport_error_text_when_detail_is_missing() -> None:
    client = CoreApiClient("http://stormhelm.test")
    errors: list[tuple[str, str]] = []
    client.error_occurred.connect(lambda purpose, error: errors.append((purpose, error)))

    reply = _FakeReply(
        error=QtNetwork.QNetworkReply.NetworkError.ConnectionRefusedError,
        error_string="Connection refused",
        body=b'{"message":"core offline"}',
    )

    client._handle_reply(reply, lambda payload: errors.append(("callback", str(payload))), "/snapshot?session_id=default")

    assert errors == [("/snapshot?session_id=default", "Connection refused")]
    assert reply.deleted is True


def test_core_api_client_parses_stream_frames_and_tracks_cursor() -> None:
    client = CoreApiClient("http://stormhelm.test")
    events: list[dict] = []
    states: list[dict] = []
    gaps: list[dict] = []
    client.stream_event_received.connect(events.append)
    client.stream_state_received.connect(states.append)
    client.stream_gap_received.connect(gaps.append)

    client._consume_stream_chunk(
        (
            'event: stormhelm.stream_state\n'
            'data: {"phase":"connected","latest_cursor":4}\n'
            "\n"
            'event: stormhelm.event\n'
            'data: {"cursor":5,"event_id":5,"event_family":"job","event_type":"job.completed","severity":"info"}\n'
            "\n"
            'event: stormhelm.replay_gap\n'
            'data: {"requested_cursor":1,"earliest_cursor":4,"latest_cursor":5}\n'
            "\n"
        ).encode("utf-8")
    )

    assert states == [{"phase": "connected", "latest_cursor": 4}]
    assert events == [
        {
            "cursor": 5,
            "event_id": 5,
            "event_family": "job",
            "event_type": "job.completed",
            "severity": "info",
        }
    ]
    assert gaps == [{"requested_cursor": 1, "earliest_cursor": 4, "latest_cursor": 5}]
    assert client._stream_last_cursor == 5

from .protocol import (
    FragmentAssembler,
    ResponseCache,
    SNPError,
    TYPE_ACK,
    TYPE_DISCOVERY_REQUEST,
    TYPE_DISCOVERY_RESPONSE,
    TYPE_FRAGMENT,
    TYPE_MESSAGE,
    TYPE_RESPONSE,
    VERSION,
    MAX_PACKET,
    decode_packet,
    encode_packet,
)
import json
import socket
import threading


class SNPServer:
    """Small UDP server wrapper for local SNP request/response handling."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9000) -> None:
        self.host = host
        self.port = port
        self._socket = None
        self._thread = None
        self._stop_event = threading.Event()
        self._cache = ResponseCache()
        self._fragment_assembler = FragmentAssembler()
        self._ready = threading.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.bind((self.host, self.port))
        self.port = self._socket.getsockname()[1]
        self._stop_event.clear()
        self._ready.clear()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2.0)

    def _serve(self) -> None:
        if self._socket is None:
            return
        self._socket.settimeout(0.2)
        self._ready.set()

        while not self._stop_event.is_set():
            try:
                packet, address = self._socket.recvfrom(MAX_PACKET + 1)
            except socket.timeout:
                continue
            except OSError:
                if self._stop_event.is_set():
                    break
                raise

            try:
                message_type, sequence, payload = decode_packet(packet)

                if message_type == TYPE_DISCOVERY_REQUEST:
                    response = encode_packet(
                        TYPE_DISCOVERY_RESPONSE,
                        sequence,
                        json.dumps({"service": "snp", "version": VERSION, "port": self.port}).encode("utf-8"),
                    )
                    self._socket.sendto(response, address)
                    continue

                if message_type == TYPE_FRAGMENT:
                    assembled = self._fragment_assembler.add_packet(packet)
                    if assembled is None:
                        continue
                    payload = assembled
                    message_type = TYPE_MESSAGE

                if message_type != TYPE_MESSAGE:
                    print(f"Ignored non-message packet from {address}")
                    continue

                request_key = (address[0], address[1], sequence)
                cached_response = self._cache.lookup(request_key)
                if cached_response is not None:
                    self._socket.sendto(cached_response, address)
                    continue

                message = payload.decode("utf-8", errors="replace")
                print(f"[{address[0]}:{address[1]}] {message}")

                response_payload = b"Received: " + payload
                response = encode_packet(TYPE_RESPONSE, sequence, response_payload)
                ack = encode_packet(TYPE_ACK, sequence, b"")
                self._cache.store(request_key, response)
                self._socket.sendto(ack, address)
                self._socket.sendto(response, address)
            except SNPError as exc:
                print(f"Rejected packet from {address}: {exc}")

    def stop(self) -> None:
        self._stop_event.set()
        if self._socket is not None:
            self._socket.close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._socket = None


def run_server(host: str, port: int) -> None:
    """Listen for SNP messages and respond to clients over UDP."""
    cache = ResponseCache()
    fragment_assembler = FragmentAssembler()

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
        server.bind((host, port))
        print(f"SNP server listening on {host}:{port} (UDP)")

        while True:
            packet, address = server.recvfrom(MAX_PACKET + 1)

            try:
                message_type, sequence, payload = decode_packet(packet)

                if message_type == TYPE_DISCOVERY_REQUEST:
                    response = encode_packet(
                        TYPE_DISCOVERY_RESPONSE,
                        sequence,
                        json.dumps({"service": "snp", "version": VERSION, "port": port}).encode("utf-8"),
                    )
                    server.sendto(response, address)
                    continue

                if message_type == TYPE_FRAGMENT:
                    assembled = fragment_assembler.add_packet(packet)
                    if assembled is None:
                        continue
                    payload = assembled
                    message_type = TYPE_MESSAGE

                if message_type != TYPE_MESSAGE:
                    print(f"Ignored non-message packet from {address}")
                    continue

                request_key = (address[0], address[1], sequence)
                cached_response = cache.lookup(request_key)
                if cached_response is not None:
                    server.sendto(cached_response, address)
                    continue

                message = payload.decode("utf-8", errors="replace")
                print(f"[{address[0]}:{address[1]}] {message}")

                response_payload = b"Received: " + payload
                response = encode_packet(TYPE_RESPONSE, sequence, response_payload)
                ack = encode_packet(TYPE_ACK, sequence, b"")
                cache.store(request_key, response)
                server.sendto(ack, address)
                server.sendto(response, address)
            except SNPError as exc:
                print(f"Rejected packet from {address}: {exc}")

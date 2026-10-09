
import unittest
import struct

from snp import (
    MAGIC,
    VERSION,
    HEADER,
    HEADER_SIZE,
    TYPE_MESSAGE,
    TYPE_RESPONSE,
    TYPE_ACK,
    TYPE_FRAGMENT,
    MAX_PAYLOAD,
    SNPError,
    RequestTracker,
    ResponseCache,
    SNPClient,
    SNPServer,
    FragmentAssembler,
    encode_packet,
    decode_packet,
    fragment_message,
    next_sequence,
    send_reliable_message,
)


class SNPTests(unittest.TestCase):
    def test_message_round_trip(self):
        payload = b"Hello from SNP!"
        packet = encode_packet(TYPE_MESSAGE, 42, payload)

        message_type, sequence, decoded = decode_packet(packet)

        self.assertEqual(message_type, TYPE_MESSAGE)
        self.assertEqual(sequence, 42)
        self.assertEqual(decoded, payload)

    def test_response_round_trip(self):
        packet = encode_packet(TYPE_RESPONSE, 7, b"OK")

        message_type, sequence, payload = decode_packet(packet)

        self.assertEqual(message_type, TYPE_RESPONSE)
        self.assertEqual(sequence, 7)
        self.assertEqual(payload, b"OK")

    def test_empty_payload(self):
        packet = encode_packet(TYPE_MESSAGE, 0, b"")
        self.assertEqual(decode_packet(packet), (TYPE_MESSAGE, 0, b""))

    def test_maximum_payload(self):
        payload = b"x" * MAX_PAYLOAD
        packet = encode_packet(TYPE_MESSAGE, 1, payload)
        self.assertEqual(decode_packet(packet)[2], payload)

    def test_oversized_payload_rejected(self):
        with self.assertRaises(SNPError):
            encode_packet(TYPE_MESSAGE, 1, b"x" * (MAX_PAYLOAD + 1))

    def test_invalid_message_type_rejected(self):
        with self.assertRaises(SNPError):
            encode_packet(99, 1, b"test")

    def test_invalid_signature_rejected(self):
        packet = bytearray(encode_packet(TYPE_MESSAGE, 1, b"test"))
        packet[0] = ord("X")

        with self.assertRaises(SNPError):
            decode_packet(bytes(packet))

    def test_unsupported_version_rejected(self):
        packet = bytearray(encode_packet(TYPE_MESSAGE, 1, b"test"))
        packet[4] = VERSION + 1

        with self.assertRaises(SNPError):
            decode_packet(bytes(packet))

    def test_truncated_header_rejected(self):
        with self.assertRaises(SNPError):
            decode_packet(b"SNPK")

    def test_payload_length_mismatch_rejected(self):
        packet = bytearray(encode_packet(TYPE_MESSAGE, 1, b"test"))

        # The payload-length field occupies bytes 10 and 11.
        struct.pack_into("!H", packet, 10, 99)

        with self.assertRaises(SNPError):
            decode_packet(bytes(packet))

    def test_sequence_out_of_range_rejected(self):
        with self.assertRaises(SNPError):
            encode_packet(TYPE_MESSAGE, -1, b"test")

        with self.assertRaises(SNPError):
            encode_packet(TYPE_MESSAGE, 0x100000000, b"test")


    def test_binary_payload_round_trip(self):
        payload = b"\x00\x01\x02\x7f\xff\x80\x00\x99"
        packet = encode_packet(TYPE_MESSAGE, 99, payload)
        self.assertEqual(decode_packet(packet), (TYPE_MESSAGE, 99, payload))

    def test_non_bytes_input_rejected(self):
        with self.assertRaises(SNPError):
            decode_packet(None)

        with self.assertRaises(SNPError):
            decode_packet("not-bytes")


    def test_request_tracker_matches_out_of_order_responses(self):
        tracker = RequestTracker()

        first = tracker.allocate()
        second = tracker.allocate()

        self.assertEqual(first, 0)
        self.assertEqual(second, 1)
        self.assertTrue(tracker.accepts_response(second))
        self.assertTrue(tracker.accepts_response(first))
        self.assertFalse(tracker.accepts_response(999))

    def test_sequence_wraparound(self):
        self.assertEqual(next_sequence(0xFFFFFFFF), 0)
        self.assertEqual(next_sequence(0xFFFFFFFE), 0xFFFFFFFF)

    def test_response_cache_reuses_duplicate_requests(self):
        cache = ResponseCache(capacity=8, ttl_seconds=30)
        key = ("127.0.0.1", 9000, 3)
        cache.store(key, b"reply")

        self.assertEqual(cache.lookup(key), b"reply")
        self.assertIsNone(cache.lookup(("127.0.0.1", 9000, 99)))

    def test_reliable_message_retries_after_timeout(self):
        calls = {"count": 0}

        class FakeSocket:
            def __init__(self, family, socktype):
                self.family = family
                self.socktype = socktype
                self.timeout = None

            def settimeout(self, value):
                self.timeout = value

            def sendto(self, packet, address):
                calls["count"] += 1

            def recvfrom(self, size):
                if calls["count"] == 1:
                    raise socket.timeout()
                return encode_packet(TYPE_RESPONSE, 0, b"OK"), ("127.0.0.1", 9000)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        import socket

        response = send_reliable_message(
            "127.0.0.1",
            9000,
            "hello",
            socket_factory=lambda *args, **kwargs: FakeSocket(*args, **kwargs),
            timeout=0.01,
            max_retries=2,
            backoff=0.0,
        )

        self.assertEqual(response, "OK")
        self.assertEqual(calls["count"], 2)

    def test_client_server_round_trip(self):
        server = SNPServer("127.0.0.1", 0)
        server.start()
        try:
            with SNPClient("127.0.0.1", server.port) as client:
                self.assertEqual(client.request("Hello from SNP API"), "Received: Hello from SNP API")
        finally:
            server.stop()

    def test_fragmented_message_round_trip(self):
        payload = b"A" * 6000
        packets = fragment_message(7, payload)

        self.assertGreater(len(packets), 1)
        assembler = FragmentAssembler()
        assembled = b""

        for packet in packets:
            message_type, sequence, fragment_payload = decode_packet(packet)
            self.assertEqual(message_type, TYPE_FRAGMENT)
            result = assembler.add_packet(packet)
            if result is not None:
                assembled = result

        self.assertEqual(assembled, payload)

    def test_fragment_malformed_and_duplicate_input(self):
        assembler = FragmentAssembler()
        malformed = encode_packet(TYPE_FRAGMENT, 7, b"bad")

        with self.assertRaises(SNPError):
            assembler.add_packet(malformed)

        payload = b"B" * 2000
        packets = fragment_message(9, payload)
        self.assertGreater(len(packets), 1)
        self.assertIsNone(assembler.add_packet(packets[0]))
        self.assertIsNone(assembler.add_packet(packets[0]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
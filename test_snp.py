
import unittest
import struct

from snp import (
    MAGIC,
    VERSION,
    HEADER,
    HEADER_SIZE,
    TYPE_MESSAGE,
    TYPE_RESPONSE,
    MAX_PAYLOAD,
    SNPError,
    encode_packet,
    decode_packet,
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
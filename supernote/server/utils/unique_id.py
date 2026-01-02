"""Module for generating unique ids."""

import random
import threading
import time

# Global lock for thread safety
_lock = threading.Lock()
_last_timestamp = -1
_sequence = 0


def next_id() -> int:
    """Generate a unique, time-ordered 64-bit integer ID.

    Format: [Timestamp (41 bits)] [Random/Sequence (22 bits)]

    This is a simplified version for a single-node server.
    """
    global _last_timestamp, _sequence

    with _lock:
        timestamp = int(time.time() * 1000)

        if timestamp < _last_timestamp:
            # Clock moved backwards, just wait a bit or raise
            raise Exception("Clock moved backwards")

        if timestamp == _last_timestamp:
            _sequence = (_sequence + 1) & 0x3FFFFF  # 22 bits
            if _sequence == 0:
                # Overflow in same ms, wait for next ms
                while timestamp <= _last_timestamp:
                    timestamp = int(time.time() * 1000)
        else:
            _sequence = random.randint(
                0, 1023
            )  # Start with random offset to minimize collisions on restart
            _last_timestamp = timestamp

        # 2021-01-01 Epoch
        epoch_offset = 1609459200000

        # Shift to make room for 22 bits of randomness/sequence
        # 41 bits (time) + 22 bits (seq) = 63 bits (Fits in Signed BigInt)
        id_val = ((timestamp - epoch_offset) << 22) | _sequence

        return id_val

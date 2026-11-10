"""A tiny GTFS-Realtime reader: just the vehicle positions, no protobuf dependency.

GTFS-RT is a Protocol Buffers message (https://gtfs.org/realtime/reference/). We only
need a handful of fields from VehiclePosition, so instead of pulling in `protobuf` and
`gtfs-realtime-bindings` this walks the wire format directly (varints, fixed32/64 and
length-delimited fields, https://protobuf.dev/programming-guides/encoding/) and skips
everything else.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from dataclasses import dataclass

# Wire types
VARINT, FIXED64, LENGTH, FIXED32 = 0, 1, 2, 5


@dataclass(frozen=True)
class Vehicle:
    trip_id: str
    start_date: str  # "20261110" ("" if the feed didn't say)
    route_id: str
    lat: float
    lon: float
    timestamp: int  # Unix time the position was recorded (0 if unknown)
    vehicle_id: str


def _varint(buf: bytes, i: int) -> tuple[int, int]:
    shift = result = 0
    while True:
        if i >= len(buf):
            raise ValueError("truncated varint")
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7
        if shift > 63:
            raise ValueError("varint too long")


def fields(buf: bytes) -> Iterator[tuple[int, int, int | bytes]]:
    """Yield (field number, wire type, value) for one message. Value is an int for
    varint/fixed fields and the raw bytes for length-delimited ones."""
    i = 0
    while i < len(buf):
        key, i = _varint(buf, i)
        number, wire = key >> 3, key & 7
        if wire == VARINT:
            value, i = _varint(buf, i)
        elif wire == FIXED64:
            value, i = int.from_bytes(buf[i : i + 8], "little"), i + 8
        elif wire == FIXED32:
            value, i = int.from_bytes(buf[i : i + 4], "little"), i + 4
        elif wire == LENGTH:
            size, i = _varint(buf, i)
            value, i = buf[i : i + size], i + size
        else:
            raise ValueError(f"unsupported wire type {wire}")
        if i > len(buf):
            raise ValueError("truncated message")
        yield number, wire, value


def _float(bits: int) -> float:
    return struct.unpack("<f", bits.to_bytes(4, "little"))[0]


def _text(value: int | bytes) -> str:
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else ""


def vehicles(feed: bytes) -> list[Vehicle]:
    """Every vehicle position in a FeedMessage that names a trip."""
    out = []
    for number, _, entity in fields(feed):
        if number != 2 or not isinstance(entity, bytes):  # FeedMessage.entity
            continue
        for n, _, vp in fields(entity):
            if n == 4 and isinstance(vp, bytes):  # FeedEntity.vehicle
                v = _vehicle(vp)
                if v is not None:
                    out.append(v)
    return out


def _vehicle(vp: bytes) -> Vehicle | None:
    trip_id = start_date = route_id = vehicle_id = ""
    lat = lon = None
    timestamp = 0
    for n, wire, value in fields(vp):
        if n == 1 and isinstance(value, bytes):  # trip: TripDescriptor
            for tn, _, tv in fields(value):
                if tn == 1:
                    trip_id = _text(tv)
                elif tn == 3:
                    start_date = _text(tv)
                elif tn == 5:
                    route_id = _text(tv)
        elif n == 2 and isinstance(value, bytes):  # position: Position
            for pn, pw, pv in fields(value):
                if pn == 1 and pw == FIXED32 and isinstance(pv, int):
                    lat = _float(pv)
                elif pn == 2 and pw == FIXED32 and isinstance(pv, int):
                    lon = _float(pv)
        elif n == 5 and wire == VARINT and isinstance(value, int):  # timestamp
            timestamp = value
        elif n == 8 and isinstance(value, bytes):  # vehicle: VehicleDescriptor
            for dn, _, dv in fields(value):
                if dn == 1:
                    vehicle_id = _text(dv)
    if not trip_id or lat is None or lon is None:
        return None
    return Vehicle(trip_id, start_date, route_id, lat, lon, timestamp, vehicle_id)

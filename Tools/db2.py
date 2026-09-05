#!/usr/bin/env python3
"""Read a WDC5 client table.

Enough of the format to get integer columns out of the creature tables, which is
all this project needs from it. Not a general reader: strings, floats and
relationship data are not decoded, because nothing here asks for them.

Why this exists at all: the race and sex of an NPC are published nowhere. The
Game Data API has no quest giver on a quest and answers 404 for creature ids;
the addons that know which NPC gives which quest do not know what that NPC is.
The client does, in CreatureDisplayInfoExtra, and the client is on the disk.

The format, briefly. A header, then one section per chunk of records. Fields are
not simply laid out: a field can sit in the record at a bit offset, or be stored
once in a common block, or be an index into a palette of values. The storage
info block says which, per field. Records can also be copies of other records,
listed separately so identical rows are stored once.
"""
import struct


class Reader:
    NONE, BITPACKED, COMMON, INDEXED, INDEXED_ARRAY, SIGNED = range(6)

    def __init__(self, data):
        if data[:4] != b"WDC5":
            raise ValueError("not a WDC5 table: %r" % data[:4])
        self.data = data
        self.version, = struct.unpack_from("<I", data, 4)
        self.schema = data[8:136].split(b"\0")[0].decode("ascii", "replace")

        off = 136
        (self.record_count, self.field_count, self.record_size, self.string_size,
         self.table_hash, self.layout_hash, self.min_id, self.max_id, self.locale,
         self.flags, self.id_index, self.total_fields) = struct.unpack_from("<IIIIIIIIIHHI", data, off)
        # Nine words, two shorts, one word: forty-four bytes, not forty. Off by
        # one field, everything after it reads as noise -- every storage kind
        # came back the same and no record parsed at all.
        off += 44
        (self.bitpacked_offset, self.lookup_count, self.storage_size,
         self.common_size, self.pallet_size, self.section_count) = struct.unpack_from("<IIIIII", data, off)
        off += 24

        self.sections = []
        for _ in range(self.section_count):
            keys = struct.unpack_from("<QIIIIIIII", data, off)
            off += 40
            self.sections.append({
                "tact": keys[0], "offset": keys[1], "records": keys[2],
                "strings": keys[3], "end": keys[4], "id_list": keys[5],
                "relations": keys[6], "offset_map": keys[7], "copies": keys[8],
            })

        # size in bits and bit position within the record, per field
        self.structure = []
        for _ in range(self.field_count):
            size, pos = struct.unpack_from("<hH", data, off)
            off += 4
            self.structure.append((32 - size, pos))

        self.storage = []
        for _ in range(self.total_fields):
            bit_offset, bit_size, extra, kind, a, b = struct.unpack_from("<HHIIII", data, off)
            off += 24
            self.storage.append({"bit": bit_offset, "size": bit_size, "extra": extra,
                                 "kind": kind, "a": a, "b": b})

        self.pallet = data[off:off + self.pallet_size]
        off += self.pallet_size
        self.common = {}
        common_block = data[off:off + self.common_size]
        off += self.common_size
        self._read_common(common_block)
        self.body = off

    def _read_common(self, block):
        """Values held once for the fields that mostly repeat, keyed by record id."""
        cursor = 0
        for index, field in enumerate(self.storage):
            if field["kind"] != self.COMMON:
                continue
            count = field["b"] // 8
            table = {}
            for _ in range(count):
                if cursor + 8 > len(block):
                    break
                key, value = struct.unpack_from("<Ii", block, cursor)
                cursor += 8
                table[key] = value
            self.common[index] = table

    @staticmethod
    def _bits(record, bit, size):
        """A little-endian bit field out of the record's bytes."""
        if size <= 0:
            return 0
        first, last = bit // 8, (bit + size - 1) // 8
        raw = int.from_bytes(record[first:last + 1], "little")
        return (raw >> (bit % 8)) & ((1 << size) - 1)

    def _pallet(self, field, index, array_index=0):
        base = 0
        for other in self.storage[:self.storage.index(field)]:
            if other["kind"] in (self.INDEXED, self.INDEXED_ARRAY):
                base += other["extra"]
        width = 4 * (field["b"] if field["kind"] == self.INDEXED_ARRAY else 1)
        at = base + index * width + array_index * 4
        if at + 4 > len(self.pallet):
            return 0
        return struct.unpack_from("<I", self.pallet, at)[0]

    def rows(self):
        """Every record as a list of integers, one per field, with its id."""
        for section in self.sections:
            if section["tact"]:
                # Encrypted section. Nothing to do about it here, and skipping is
                # right: the rest of the table is still usable.
                continue
            at = section["offset"]
            size = section["records"] * self.record_size
            records = self.data[at:at + size]
            at += size
            at += section["strings"]
            ids = []
            if section["id_list"]:
                ids = list(struct.unpack_from("<%dI" % (section["id_list"] // 4),
                                              self.data, at))
                at += section["id_list"]
            copies = []
            if section["copies"]:
                for i in range(section["copies"] // 8):
                    new, old = struct.unpack_from("<II", self.data, at + i * 8)
                    copies.append((new, old))
                at += section["copies"]

            by_id = {}
            for index in range(section["records"]):
                record = records[index * self.record_size:(index + 1) * self.record_size]
                values = [self._value(record, f) for f in range(self.total_fields)]
                row_id = ids[index] if ids else values[self.id_index]
                # A field stored in the common block is keyed by id, not position.
                for field_index, table in self.common.items():
                    values[field_index] = table.get(row_id, self.storage[field_index]["a"])
                by_id[row_id] = values
                yield row_id, values
            for new, old in copies:
                if old in by_id:
                    yield new, list(by_id[old])

    def _value(self, record, index):
        field = self.storage[index]
        kind = field["kind"]
        if kind == self.NONE:
            return self._bits(record, field["bit"], field["size"])
        if kind in (self.BITPACKED, self.SIGNED):
            value = self._bits(record, field["bit"], field["size"])
            if kind == self.SIGNED and value & (1 << (field["size"] - 1)):
                value -= 1 << field["size"]
            return value
        if kind in (self.INDEXED, self.INDEXED_ARRAY):
            return self._pallet(field, self._bits(record, field["bit"], field["size"]))
        return 0                                    # common: filled in by rows()


def read(path):
    with open(path, "rb") as fh:
        return Reader(fh.read())

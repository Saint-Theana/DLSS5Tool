"""Read allocation metadata in this diagnostic process, without reading payloads.

VirtualQuery separates address-space types; QueryVirtualMemoryInformation also
counts private commit in mapped views (including copy-on-write). Neither API
identifies the caller of an anonymous allocation. HeapSummary is limited to the
default process heap: private heaps owned by other DLLs can disappear concurrently
and must not be walked using stale GetProcessHeaps handles.

Set DLSS5TOOL_P0_MEMORY_MAP=1 for the bounded native frame diagnostic. No registry,
debug privilege, system-wide tracing, heap trimming or production hook is used.
"""
import argparse
import ctypes as C
import json
import os
import time


class Basic(C.Structure):
    _fields_ = [('base', C.c_void_p), ('allocation_base', C.c_void_p),
                ('allocation_protect', C.c_uint32), ('partition', C.c_uint16),
                ('region_size', C.c_size_t), ('state', C.c_uint32),
                ('protect', C.c_uint32), ('type', C.c_uint32)]


class Region(C.Structure):
    _fields_ = [('allocation_base', C.c_void_p), ('allocation_protect', C.c_uint32),
                ('flags', C.c_uint32), ('region_size', C.c_size_t),
                ('commit_size', C.c_size_t)]


class Heap(C.Structure):
    _fields_ = [('cb', C.c_uint32)] + [(key, C.c_size_t) for key in
        ('allocated', 'committed', 'reserved', 'max_reserve')]


class Inspector:
    def __init__(self):
        if os.name != 'nt' or C.sizeof(C.c_void_p) != 8:
            raise RuntimeError('This diagnostic requires 64-bit Windows Python')
        if (C.sizeof(Basic), C.sizeof(Region), C.sizeof(Heap)) != (48, 32, 40):
            raise RuntimeError('Unexpected Win32 structure layout')
        self.k = C.WinDLL('kernel32', use_last_error=True)
        for name, args, result in (
            ('GetCurrentProcess', [], C.c_void_p),
            ('GetProcessHeap', [], C.c_void_p),
            ('GetProcessHeaps', [C.c_uint32, C.c_void_p], C.c_uint32),
            ('GetProcessTimes', [C.c_void_p]+[C.c_void_p]*4, C.c_int),
            ('VirtualQuery', [C.c_void_p, C.POINTER(Basic), C.c_size_t], C.c_size_t),
            ('HeapSummary', [C.c_void_p, C.c_uint32, C.POINTER(Heap)], C.c_int),
        ):
            fn = getattr(self.k, name)
            fn.argtypes, fn.restype = args, result
        self.q = C.WinDLL('api-ms-win-core-memory-l1-1-4', use_last_error=True)
        self.q.QueryVirtualMemoryInformation.argtypes = [C.c_void_p, C.c_void_p,
            C.c_int, C.POINTER(Region), C.c_size_t, C.c_void_p]
        self.q.QueryVirtualMemoryInformation.restype = C.c_int
        self.p = C.WinDLL('psapi', use_last_error=True)
        self.p.GetMappedFileNameW.argtypes = [C.c_void_p, C.c_void_p, C.c_wchar_p, C.c_uint32]
        self.p.GetMappedFileNameW.restype = C.c_uint32
        self.process = self.k.GetCurrentProcess()
        self.created = C.c_uint64()
        unused = [C.c_uint64() for _ in range(3)]
        if not self.k.GetProcessTimes(self.process, C.byref(self.created),
                                     *(C.byref(v) for v in unused)):
            raise C.WinError(C.get_last_error())

    def snapshot(self):
        begin = time.time()
        default = self.k.GetProcessHeap()
        heap = Heap(cb=C.sizeof(Heap))
        heap_info = dict(handle=hex(default), scope='default process heap only')
        if self.k.HeapSummary(default, 0, C.byref(heap)):
            heap_info.update({name: getattr(heap, name) for name in
                              ('allocated', 'committed', 'reserved', 'max_reserve')})
        else:
            heap_info['error'] = C.get_last_error()
        handles = (C.c_void_p*1024)()
        count = self.k.GetProcessHeaps(len(handles), handles)
        heap_handles = [hex(h) for h in handles[:min(count, len(handles))]]
        allocations = {}
        address, query_count = 0, 0
        type_names = {0x20000: 'private', 0x40000: 'mapped', 0x1000000: 'image'}
        committed = {name: 0 for name in type_names.values()}
        while address < 0x800000000000:
            basic = Basic()
            if not self.k.VirtualQuery(address, C.byref(basic), C.sizeof(basic)):
                error = C.get_last_error()
                if error == 87:  # End of the address space.
                    break
                raise C.WinError(error)
            query_count += 1
            next_address = (basic.base or 0)+basic.region_size
            if next_address <= address or query_count > 1000000:
                raise RuntimeError('VirtualQuery did not advance within its diagnostic bound')
            address = next_address
            if basic.state == 0x10000:  # MEM_FREE
                continue
            key = hex(basic.allocation_base or 0)
            item = allocations.get(key)
            if item is None:
                item = allocations[key] = dict(base=key,
                    type=type_names.get(basic.type, str(basic.type)),
                    committed_bytes=0, reserved_bytes=0, regions=0, protections={})
                region = Region()
                if self.q.QueryVirtualMemoryInformation(self.process, basic.allocation_base,
                                                       0, C.byref(region), C.sizeof(region), None):
                    item.update(allocation_size=region.region_size,
                                allocation_private_commit=region.commit_size,
                                mapping_kind=[name for bit, name in enumerate(
                                    ('private','data_file','image','page_file','physical','direct'))
                                    if region.flags & (1 << bit)])
                else:
                    item['allocation_query_error'] = C.get_last_error()
                if basic.type in (0x40000, 0x1000000):
                    path = C.create_unicode_buffer(32768)
                    if self.p.GetMappedFileNameW(self.process, basic.allocation_base, path, len(path)):
                        item['mapped_path'] = path.value
            item['regions'] += 1
            if basic.state == 0x1000:
                item['committed_bytes'] += basic.region_size
                name = type_names.get(basic.type)
                if name:
                    committed[name] += basic.region_size
                protection = hex(basic.protect)
                item['protections'][protection] = item['protections'].get(protection, 0)+basic.region_size
            elif basic.state == 0x2000:
                item['reserved_bytes'] += basic.region_size
        private_commit = {name: 0 for name in type_names.values()}
        errors = 0
        for item in allocations.values():
            if 'allocation_query_error' in item:
                errors += 1
            elif item['type'] in private_commit:
                private_commit[item['type']] += item['allocation_private_commit']
        return dict(pid=os.getpid(), created=self.created.value, wall=begin,
            elapsed_seconds=time.time()-begin, scope='own process, metadata only; no allocation call stacks',
            default_heap=heap_info, heap_count=count, heap_handles=heap_handles,
            virtual_committed_by_type=committed, private_commit_by_type=private_commit,
            private_commit_query_errors=errors, query_count=query_count,
            allocations=list(allocations.values()))

    def self_check(self):
        """Prove accounting against one known VirtualAlloc allocation and release."""
        self.k.VirtualAlloc.argtypes = [C.c_void_p, C.c_size_t, C.c_uint32, C.c_uint32]
        self.k.VirtualAlloc.restype = C.c_void_p
        self.k.VirtualFree.argtypes = [C.c_void_p, C.c_size_t, C.c_uint32]
        self.k.VirtualFree.restype = C.c_int
        size = 16*1024**2
        address = self.k.VirtualAlloc(None, size, 0x3000, 4)
        if not address:
            raise C.WinError(C.get_last_error())
        try:
            snap = self.snapshot()
            item = next(a for a in snap['allocations'] if a['base'] == hex(address))
            assert item['type'] == 'private' and item['committed_bytes'] == size, item
            assert item['allocation_private_commit'] == size, item
        finally:
            if not self.k.VirtualFree(address, 0, 0x8000):
                raise C.WinError(C.get_last_error())
        basic = Basic()
        assert self.k.VirtualQuery(address, C.byref(basic), C.sizeof(basic))
        assert basic.state == 0x10000, basic.state
        return dict(status='passed', known_private_commit_bytes=size, released=True,
                    default_heap=snap['default_heap'], query_errors=snap['private_commit_query_errors'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-check', action='store_true')
    args = parser.parse_args()
    inspector = Inspector()
    print(json.dumps(inspector.self_check() if args.self_check else inspector.snapshot(), indent=2))

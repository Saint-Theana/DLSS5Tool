"""Windows kill-on-close lifetime container for an already owned Popen child."""
import ctypes as C
import os


class _Basic(C.Structure):
    _fields_=[('process_time',C.c_int64),('job_time',C.c_int64),('flags',C.c_uint32),
              ('min_working',C.c_size_t),('max_working',C.c_size_t),('active',C.c_uint32),
              ('affinity',C.c_size_t),('priority',C.c_uint32),('scheduling',C.c_uint32)]


class _Extended(C.Structure):
    _fields_=[('basic',_Basic),('io',C.c_uint64*6),('process_memory',C.c_size_t),
              ('job_memory',C.c_size_t),('peak_process',C.c_size_t),('peak_job',C.c_size_t)]


class KillOnCloseJob:
    """The child cannot inherit this handle; owner death closes it in the kernel.

    Callers keep the Popen process handle and must gate child native work until
    assignment succeeds. This class never opens a process by name or PID.
    """
    def __init__(self, process):
        if os.name!='nt':
            raise OSError('Windows job required')
        self._kernel=C.WinDLL('kernel32',use_last_error=True)
        for name,args,result in (
            ('CreateJobObjectW',[C.c_void_p,C.c_wchar_p],C.c_void_p),
            ('SetInformationJobObject',[C.c_void_p,C.c_int,C.c_void_p,C.c_uint32],C.c_int),
            ('AssignProcessToJobObject',[C.c_void_p,C.c_void_p],C.c_int),
            ('CloseHandle',[C.c_void_p],C.c_int),
        ):
            function=getattr(self._kernel,name); function.argtypes=args; function.restype=result
        self._handle=self._kernel.CreateJobObjectW(None,None)
        if not self._handle: raise C.WinError(C.get_last_error())
        try:
            limits=_Extended(); limits.basic.flags=0x2000
            if not self._kernel.SetInformationJobObject(self._handle,9,C.byref(limits),C.sizeof(limits)):
                raise C.WinError(C.get_last_error())
            if not self._kernel.AssignProcessToJobObject(self._handle,int(process._handle)):
                raise C.WinError(C.get_last_error())
        except BaseException:
            self.close()
            raise

    def close(self):
        if self._handle:
            if not self._kernel.CloseHandle(self._handle):
                raise C.WinError(C.get_last_error())
            self._handle=None

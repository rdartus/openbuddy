import amoled_qspi
import _qspi_test as mock
import gc


def raises(kind, function, *args, **kwargs):
    try:
        function(*args, **kwargs)
    except kind:
        return
    raise AssertionError("expected exception")


cases = 0
for quad in (False, True):
    for size in (0, 1, 3, 4, 4091, 4092, 4093, 8184, 8185, 19968):
        data = bytearray(size)
        for i in range(size):
            data[i] = i % 251
        mock.configure(0x2c, data, quad, 0)
        bus = amoled_qspi.Bus(baudrate=10000000)
        bus.write(0x2c, memoryview(data), quad=quad)
        bus.deinit()
        bus.deinit()
        raises(OSError, bus.write, 0x2c, data, quad)
        mock.check(True)
        cases += 1

for failure in range(1, 8):
    data = bytes(9000)
    mock.configure(0x2c, data, True, failure)
    if failure <= 3:
        raises(MemoryError if failure == 1 else OSError, amoled_qspi.Bus)
    else:
        bus = amoled_qspi.Bus()
        raises(OSError, bus.write, 0x2c, data, True)
        raises(OSError, bus.write, 0x2c, data, True)
        bus.deinit()
    gc.collect()
    mock.check(False)
    cases += 1

mock.configure(0x11, b"", False, 0)
bus = amoled_qspi.Bus()
raises(OSError, amoled_qspi.Bus)
gc.collect()  # Failed constructor's finaliser must not touch the live bus.
for cmd in (-1, 256):
    raises(ValueError, bus.write, cmd)
for cmd in (None, "44", 1.5):
    raises(TypeError, bus.write, cmd)
raises(TypeError, bus.write, 0x11, object())
raises(TypeError, bus.write)
raises(TypeError, bus.write, 0x11, unknown=True)
bus.write(command=0x11, data=None)
bus.deinit()
mock.check(True)
cases += 1

for command in (0, 255):
    data = b"\x01\x80\xff"
    mock.configure(command, data, False, 0)
    bus = amoled_qspi.Bus(10000000)
    bus.write(command, data)
    bus.deinit()
    # A late finaliser on an old object must not free a new owner's bus.
    replacement = amoled_qspi.Bus()
    bus.__del__()
    replacement.deinit()
    mock.check(False)
    cases += 1

mock.configure(0, b"", False, 0)
mock.external(True)
raises(OSError, amoled_qspi.Bus)
gc.collect()
mock.check(False)
mock.external(False)
cases += 1

for baudrate in (0, -1, 80000001):
    raises(ValueError, amoled_qspi.Bus, baudrate=baudrate)
raises(TypeError, amoled_qspi.Bus, unknown=True)
raises(TypeError, amoled_qspi.Bus, 1, 2)

for failure in (10, 11):
    mock.configure(0, b"", False, 0)
    bus = amoled_qspi.Bus()
    mock.failure(failure)
    raises(OSError, bus.deinit)
    raises(OSError, bus.write, 0)
    mock.failure(0)
    bus.deinit()
    bus.deinit()
    mock.check(False)
    cases += 1


def abandoned():
    amoled_qspi.Bus()


mock.configure(0, b"", False, 0)
abandoned()
gc.collect()
mock.check(False)
cases += 1
print("native QSPI:", cases, "cases passed")

# Leave a rooted object live. The C harness invokes ESP32's gc_sweep_all hook
# at exit and verifies that the native finaliser releases its resources.
mock.configure(0, b"", False, 0)
soft_reset_bus = amoled_qspi.Bus()

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
assert amoled_qspi.API_VERSION == 3
for cs in (9, 46):
    for failure in (0, 3, 5, 6):
        data = bytes(9000)
        mock.configure(0x2c, data, True, failure, cs)
        if failure == 3:
            raises(OSError, amoled_qspi.Bus, cs=cs)
        else:
            bus = amoled_qspi.Bus(cs=cs)
            if failure:
                raises(OSError, bus.write, 0x2c, data, True)
            else:
                bus.write(0x2c, data, True)
            bus.deinit()
        gc.collect()
        mock.check(not failure)
        cases += 1

for cs in (-1, 0, 10, 45, 49):
    raises(ValueError, amoled_qspi.Bus, cs=cs)

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


def physical_pixel(shadow, x, y):
    position = (y * 280 + x) * 2
    return shadow[position:position + 2]


mock.configure(0, b"", False, 0, 46)
bus = amoled_qspi.Bus(cs=46)
shadow = bytearray(280 * 456 * 2)
scratch = bytearray(16)
bus.fill_buffer(shadow, 0x07e0)
assert physical_pixel(shadow, 0, 0) == b"\x07\xe0"
assert physical_pixel(shadow, 279, 455) == b"\x07\xe0"
for inverted in (False, True):
    bus.fill_buffer(shadow, 0)
    left, top = (224, 68) if inverted else (54, 386)
    bus.fill_rect(shadow, left, top, 2, 2, 0x1234)
    bus.blit_rotated(shadow, b"\xab\xcd", 0, 1, 1, 1, inverted)
    bus.pack_rect(shadow, scratch, left, top, 2, 2)
    expected = (b"\xab\xcd\x12\x34\x12\x34\x12\x34" if inverted
                else b"\x12\x34\x12\x34\x12\x34\xab\xcd")
    assert scratch[:8] == expected
    assert physical_pixel(shadow, 0, 0) == b"\x00\x00"
    cases += 1

source = b"\xf8\x00\x07\xe0\x00\x1f\x12\x34\xab\xcd\xff\xff"
for inverted, left, top, expected in (
    (False, 54, 384, b"\x00\x00\x00\x00\x00\x1f\xff\xff\x07\xe0\xab\xcd\xf8\x00\x12\x34"),
    (True, 224, 68, b"\x12\x34\xf8\x00\xab\xcd\x07\xe0\xff\xff\x00\x1f\x00\x00\x00\x00"),
):
    bus.fill_buffer(shadow, 0)
    bus.blit_rotated(shadow, memoryview(source), 0, 0, 3, 2, inverted)
    bus.pack_rect(shadow, scratch, left, top, 2, 4)
    assert scratch == expected
    cases += 1

unchanged = physical_pixel(shadow, 224, 68)
raises(ValueError, bus.fill_buffer, bytearray(3), 0)
raises(TypeError, bus.fill_buffer, bytes(3), 0)
for color in (-1, 0x10000):
    raises(ValueError, bus.fill_buffer, shadow, color)
    raises(ValueError, bus.fill_rect, shadow, 0, 0, 1, 1, color)
for rect in ((-1, 0, 1, 1), (279, 0, 2, 1), (0, 456, 1, 1),
             (0, 0, 0, 1), (0, 0, 10000000, 1)):
    raises(ValueError, bus.fill_rect, *((shadow,) + rect + (0,)))
    raises(ValueError, bus.pack_rect, shadow, scratch, *rect)
for rect in ((-1, 0, 1, 1), (320, 0, 1, 1), (0, 171, 1, 2),
             (0, 0, 0, 1), (0, 0, 10000000, 1)):
    raises(ValueError, bus.blit_rotated, *((shadow, b"\x12\x34") + rect + (False,)))
raises(ValueError, bus.blit_rotated, shadow, b"", 0, 0, 1, 1, False)
raises(ValueError, bus.blit_rotated, shadow, memoryview(shadow)[:2], 0, 0, 1, 1, False)
for rect in ((1, 0, 2, 2), (0, 0, 3, 2), (0, 0, 280, 456)):
    raises(ValueError, bus.pack_rect, shadow, scratch, *rect)
raises(ValueError, bus.pack_rect, shadow, shadow, 0, 0, 2, 2)
assert physical_pixel(shadow, 224, 68) == unchanged
bus.deinit()
for method, args in ((bus.fill_buffer, (shadow, 0)),
                     (bus.fill_rect, (shadow, 0, 0, 2, 2, 0)),
                     (bus.blit_rotated, (shadow, b"\x00\x00", 0, 0, 1, 1, False)),
                     (bus.pack_rect, (shadow, scratch, 0, 0, 2, 2))):
    raises(OSError, method, *args)
mock.check(False)
cases += 1

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
mock.configure(0, b"", False, 0, 46)
soft_reset_bus = amoled_qspi.Bus(cs=46)

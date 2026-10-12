"""Continuous crane move after the approved T305 ignition/join window."""
from mathutils import Vector

LOCK_END = 111
END = 217
MOVE_END = 205


def quintic(start, end, velocity, acceleration, end_velocity, u, duration):
    """Position curve with matched velocity/acceleration at both ends."""
    v0 = velocity * duration
    a0 = acceleration * duration**2
    v1 = end_velocity * duration
    delta = end - start
    return (start + v0*u + a0*u*u/2
            + (10*delta - 6*v0 - 1.5*a0 - 4*v1)*u**3
            + (-15*delta + 8*v0 + 1.5*a0 + 7*v1)*u**4
            + (6*delta - 3*v0 - .5*a0 - 3*v1)*u**5)


def camera_pose(frame, base):
    t = (frame - 1) / 24
    if frame <= LOCK_END:
        # Keep the approved formula and operation order, including orientation.
        loc = base + Vector((1.5*t - .52*t*t, -2.14*t, 0))
        climb = max(0, (frame - 120) / 97)
        target = Vector((0, 80, 45 + 64*climb**1.8))
    else:
        start_t = (LOCK_END - 1) / 24
        start = base + Vector((1.5*start_t - .52*start_t**2, -2.14*start_t, 0))
        duration = (MOVE_END - LOCK_END) / 24
        u = min(1., (frame - LOCK_END) / (MOVE_END - LOCK_END))
        # Sweep past the foreground pillar and rise with the launch. Keeping
        # the 12 mm lens lets the moving arch supply the sense of scale.
        loc = quintic(start, Vector((-42, -37, 22)),
                      Vector((1.5 - 1.04*start_t, -2.14, 0)),
                      Vector((-1.04, 0, 0)), Vector((-.6, -.3, .2)),
                      u, duration)
        loc += Vector((-.6, -.3, .2)) * max(0., (frame - MOVE_END)/24)
        # Stay inside the shallow ground haze until the tilt clears its upper
        # boundary. An early crane exposes the finite fog box as a flat strip.
        rise_u = min(1., max(0., (frame - 144)/(MOVE_END - 144)))
        loc.z = quintic(base.z, 22., 0., 0., .2, rise_u, (MOVE_END - 144)/24)
        loc.z += .2 * max(0., (frame - MOVE_END)/24)
        # The tilt also eases to rest; the machine continues ascending through
        # the composition while the camera finishes its move.
        height = quintic(45., 140., 0., 0., 0., u, duration)
        target = Vector((0, 80, height))
    return loc, (target - loc).to_track_quat('-Z', 'Y')


def animate_camera(camera, base):
    for frame in range(1, END + 1):
        camera.location, camera.rotation_quaternion = camera_pose(frame, base)
        camera.keyframe_insert(data_path='location', frame=frame)
        camera.keyframe_insert(data_path='rotation_quaternion', frame=frame)
    for layer in camera.animation_data.action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for curve in bag.fcurves:
                    for key in curve.keyframe_points:
                        key.interpolation = 'LINEAR'

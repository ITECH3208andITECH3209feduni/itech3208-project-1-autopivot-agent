"""Fit a vehicle's lower silhouette inside a measured turntable top.

Contacts are silhouette estimates, not a trained wheel detector. The original
perspective is retained: each contact keeps its own vertical offset.
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def contacts(image):
    """Find lower silhouette support points in the left/right wheel regions."""
    rgba = np.asarray(image.convert('RGBA'))
    mask = rgba[:, :, 3] >= 128
    ys, xs = np.where(mask)
    if xs.size == 0:
        return []
    left, right, top, bottom = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    width, height = right-left+1, bottom-top+1
    envelope = np.full(image.width, -1., dtype=float)
    for x in range(left, right+1):
        column = np.flatnonzero(mask[:, x])
        if column.size:
            envelope[x] = column[-1]
    # Median rejects isolated hanging segmentation pixels without moving the
    # actual opaque tyre edge selected below.
    radius = max(1, round(width * .012))
    smooth = np.array([np.median(envelope[max(left,x-radius):min(right+1,x+radius+1)])
                       for x in range(left, right+1)])
    found = []
    for low, high in ((.05, .47), (.53, .95)):
        lo, hi = left+int(width*low), min(right+1,left+int(width*high))
        candidates = np.arange(lo, hi)
        if not candidates.size:
            continue
        depths = smooth[candidates-left]
        valid = depths >= top + height*.62
        if not valid.any():
            continue
        candidates, depths = candidates[valid], depths[valid]
        near = candidates[depths >= depths.max()-max(2,height*.025)]
        # Prefer dark rubber among similarly low support pixels.
        scores = []
        for x in near:
            y = int(envelope[x])
            patch = rgba[max(top,y-max(3,int(height*.045))):y+1, x, :3]
            scores.append(float(patch.mean()) if patch.size else 255.)
        best = near[np.asarray(scores) <= min(scores)+22]
        x = int(best[len(best)//2])
        y = int(envelope[x])
        found.append((x, y))
    if not found:
        x = int(np.median(xs[ys >= bottom-1]))
        found = [(x, int(envelope[x]))]
    return found


def fit(cutout, box, size):
    """Uniformly scale and translate; all estimated tyre contacts fit on top."""
    cw, ch = size
    x1,y1,x2,y2 = box
    cx,cy = (x1+x2)*cw/2, (y1+y2)*ch/2
    rx,ry = (x2-x1)*cw/2, (y2-y1)*ch/2
    alpha = np.asarray(cutout.getchannel('A')) >= 128
    ys,xs = np.where(alpha)
    if not xs.size:
        raise ValueError('Cannot place an empty vehicle cutout')
    visible_w,visible_h = xs.max()-xs.min()+1,ys.max()-ys.min()+1
    # Fill the stage while retaining roof clearance for taller front views.
    scale = min((2*rx*.90)/visible_w, ch*.35/visible_h)
    # Keep a small side inset, but use almost the complete measured ellipse for
    # the vertical drop. The previous .79 vertical inset stopped the car before
    # the visible top surface and made the farther/rear tyre appear to float.
    safe_rx,safe_ry = rx*.97,ry*.94
    for _ in range(100):
        vehicle = cutout.resize((max(1,round(cutout.width*scale)),max(1,round(cutout.height*scale))),Image.Resampling.LANCZOS)
        pts = contacts(vehicle)
        a = np.asarray(vehicle.getchannel('A')) >= 128
        vy,vx = np.where(a)
        x = round(cx-(int(vx.min())+int(vx.max()))/2)
        # Correct the small vertical perspective mismatch between the source
        # wheel line and the stage arc. A front-quarter photo often has the
        # far/rear wheel several pixels higher than the turntable predicts. A
        # gentle vertical shear keeps both tyres on the same physical surface;
        # it is capped so unusual silhouettes are left undistorted.
        if len(pts) >= 2 and abs(pts[-1][0]-pts[0][0]) > 20:
            surface_y = []
            for px, _ in pts:
                dx = (x+px-cx)/safe_rx
                if abs(dx) >= 1:
                    surface_y = []
                    break
                surface_y.append(cy + safe_ry*np.sqrt(1-dx*dx))
            if len(surface_y) == len(pts):
                dx_pts = pts[-1][0]-pts[0][0]
                slope = ((surface_y[-1]-surface_y[0]) - (pts[-1][1]-pts[0][1])) / dx_pts
                if abs(slope) <= .20:
                    # y_out = y_in + slope * (x - reference_x)
                    ref_x = pts[0][0]
                    vehicle = vehicle.transform(
                        vehicle.size,
                        Image.Transform.AFFINE,
                        (1, 0, 0, -slope, 1, slope*ref_x),
                        resample=Image.Resampling.BICUBIC,
                    )
                    pts = contacts(vehicle)
                    a = np.asarray(vehicle.getchannel('A')) >= 128
                    vy,vx = np.where(a)
                    x = round(cx-(int(vx.min())+int(vx.max()))/2)
        lower,upper = -float('inf'),float('inf')
        # The top of the turntable is the lower arc of the measured ellipse.
        # Aligning the support points to this arc follows the platform's
        # perspective: a rear tyre is higher at the far side, while the nearer
        # tyre lands lower toward the front rim.
        surface_offsets = []
        for px,py in pts:
            dx = (x+px-cx)/safe_rx
            if abs(dx)>=1:
                lower,upper=1,0
                break
            reach = safe_ry*np.sqrt(1-dx*dx)
            lower=max(lower,cy-reach-py)
            upper=min(upper,cy+reach-py)
            surface_offsets.append(cy + safe_ry*np.sqrt(1-dx*dx) - py)
        # Keep the roof within the scene as well as fitting the wheel footprint.
        lower=max(lower,ch*.14-int(vy.min()))
        if pts and lower+2 <= upper:
            # Use the most restrictive support so no tyre remains above the
            # surface. Other supports retain their image perspective and are
            # covered by the per-tyre contact shadow when the source view is
            # strongly oblique.
            desired = min(surface_offsets) if surface_offsets else cy + ry*.88 - max(py for _,py in pts)
            y = int(round(np.clip(desired,lower+1,upper-1)))
            return vehicle,x,y,pts
        scale*=.97
    raise ValueError('The cutout cannot be placed inside the display base')


def ground_shadow(size, vehicle, x, y, pts):
    """Soft underbody pool following the slope of the estimated tyre contacts."""
    alpha = np.asarray(vehicle.getchannel('A')) >= 128
    ys, xs = np.where(alpha)
    width = int(xs.max()-xs.min()+1)
    supports = sorted((x+px, y+py) for px, py in pts)
    cx = x + (int(xs.min())+int(xs.max()))/2
    if len(supports) > 1 and supports[-1][0] != supports[0][0]:
        slope = (supports[-1][1]-supports[0][1])/(supports[-1][0]-supports[0][0])
        cy = supports[0][1] + slope*(cx-supports[0][0])
    else:
        slope, cy = 0., supports[0][1]
    shadow = Image.new('RGBA', size, (0,0,0,0))
    for radius, depth, opacity, blur in ((.49,.047,85,.010),(.43,.024,120,.004)):
        mask = Image.new('L', size, 0)
        polygon = []
        for angle in np.linspace(0, 2*np.pi, 80, endpoint=False):
            dx = width*radius*np.cos(angle)
            polygon.append((cx+dx,cy+slope*dx+size[1]*depth*np.sin(angle)))
        ImageDraw.Draw(mask).polygon(polygon,fill=opacity)
        mask = mask.filter(ImageFilter.GaussianBlur(max(1,size[1]*blur)))
        layer = Image.new('RGBA',size,(0,0,0,0))
        layer.putalpha(mask)
        shadow.alpha_composite(layer)
    return shadow


def contact_shadow(size, vehicle, x, y, pts):
    """Dark, short tyre patches positioned at each actual support pixel."""
    width=max(5,round(vehicle.width*.035))
    height=max(2,round(size[1]*.0035))
    mask=Image.new('L',size,0)
    draw=ImageDraw.Draw(mask)
    for px,py in pts:
        cx,cy=x+px,y+py
        draw.ellipse((cx-width,cy-height,cx+width,cy+height),fill=205)
    mask=mask.filter(ImageFilter.GaussianBlur(max(.8,size[1]*.0015)))
    shadow=Image.new('RGBA',size,(0,0,0,0)); shadow.putalpha(mask)
    return shadow

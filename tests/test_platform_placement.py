"""Geometry checks use synthetic silhouettes, not AI-segmented vehicle photos."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import unittest
from PIL import Image,ImageDraw
import compositing as c
import platform_placement as p


def vehicle(w,h,oblique=False):
    im=Image.new('RGBA',(w,h),(0,0,0,0));d=ImageDraw.Draw(im)
    d.rounded_rectangle((w*.03,h*.28,w*.97,h*.84),radius=12,fill=(145,30,35,255))
    d.polygon([(w*.2,h*.3),(w*.32,h*.04),(w*.72,h*.04),(w*.88,h*.3)],fill=(65,85,92,255))
    for x,dy in ((w*.21,0),(w*.79,-h*.18 if oblique else 0)):
        d.ellipse((x-w*.065,h*.66+dy,x+w*.065,h*.98+dy),fill=(18,18,18,255))
    return im


class PlacementTests(unittest.TestCase):
    def test_contacts_inside_surface_at_multiple_aspects(self):
        for w,h,oblique in [(400,380,False),(1000,350,False),(650,420,True),(250,550,False)]:
            for size in [(1280,960),(640,480)]:
                with self.subTest(w=w,h=h,size=size):
                    v,x,y,pts=p.fit(vehicle(w,h,oblique),c.STUDIO_FULL.platform_box,size)
                    mask=c._platform_mask(c.STUDIO_FULL,size)
                    self.assertGreaterEqual(len(pts),1)
                    for px,py in pts:self.assertEqual(mask.getpixel((x+px,y+py)),255)
                    self.assertGreaterEqual(y,0)
                    self.assertLessEqual(x+v.width,size[0])
                    bounds = v.getchannel("A").point(lambda a: 255 if a >= 128 else 0).getbbox()
                    self.assertLessEqual(bounds[3]-bounds[1],size[1]*.35+2)
    def test_contact_shadow_at_each_support(self):
        v,x,y,pts=p.fit(vehicle(650,420,True),c.STUDIO_FULL.platform_box,(1280,960))
        shadow=p.contact_shadow((1280,960),v,x,y,pts)
        for px,py in pts:self.assertGreater(shadow.getpixel((x+px,y+py))[3],70)
    def test_compose_metadata(self):
        bg=Image.open(Path(c.BACKGROUND_DIR)/'studio-full.png')
        out,meta=c.compose(vehicle(700,320),bg,c.STUDIO_FULL)
        self.assertEqual(out.size,(1280,960));self.assertTrue(meta['platform_mask_applied'])
        self.assertEqual(len(meta['tyre_contacts']),2)
    def test_closeup_unchanged_path(self):
        bg=Image.new('RGB',(1280,960),'white')
        _,meta=c.compose(vehicle(400,380),bg,c.STUDIO_CLOSEUP)
        self.assertFalse(meta['platform_mask_applied'])
    def test_empty_rejected(self):
        with self.assertRaises(ValueError):p.fit(Image.new('RGBA',(40,40)),c.STUDIO_FULL.platform_box,(1280,960))


def solid_bounds(v):
    """Bounding box of the opaque vehicle, the same alpha >= 128 fit() measures."""
    return v.getchannel("A").point(lambda a: 255 if a >= 128 else 0).getbbox()


class OneSizeTests(unittest.TestCase):
    """The stage decides where a car stands, never how big it is.

    Sizing each cutout to fill the stage is what made the gallery change size
    on the studio platform: a wide side-on view ran out of stage width and a
    narrow head-on one ran out of height, so the same car came out a third
    taller head-on than side-on.
    """

    SHAPES = [(400, 380, False), (1000, 350, False), (650, 420, True), (250, 550, False)]

    def test_one_visible_height_whatever_the_aspect(self):
        for size in [(1280, 960), (640, 480)]:
            heights = {}
            for w, h, oblique in self.SHAPES:
                v, _, _, _ = p.fit(vehicle(w, h, oblique), c.STUDIO_FULL.platform_box, size)
                top, bottom = solid_bounds(v)[1], solid_bounds(v)[3]
                heights[(w, h)] = bottom - top
            with self.subTest(size=size):
                self.assertLess(max(heights.values()) / min(heights.values()), 1.03, heights)

    def test_a_requested_scale_is_kept_when_every_tyre_fits(self):
        cutout = vehicle(700, 320)
        v, x, y, pts = p.fit(cutout, c.STUDIO_FULL.platform_box, (1280, 960), scale=.8)
        self.assertEqual(v.size, (round(cutout.width * .8), round(cutout.height * .8)))
        mask = c._platform_mask(c.STUDIO_FULL, (1280, 960))
        for px, py in pts:
            self.assertEqual(mask.getpixel((x + px, y + py)), 255)

    def test_the_stage_still_bounds_whatever_scale_is_asked_for(self):
        box = c.STUDIO_FULL.platform_box
        for size in [(1280, 960), (640, 480)]:
            for w, h, oblique in self.SHAPES:
                with self.subTest(w=w, h=h, size=size):
                    v, x, y, pts = p.fit(vehicle(w, h, oblique), box, size, scale=10)
                    left, top, right, bottom = solid_bounds(v)
                    self.assertLessEqual(bottom - top, size[1] * .35 + 2)
                    self.assertLessEqual(right - left, size[0] * (box[2] - box[0]) + 2)
                    mask = c._platform_mask(c.STUDIO_FULL, size)
                    for px, py in pts:
                        self.assertEqual(mask.getpixel((x + px, y + py)), 255)


if __name__=='__main__':unittest.main()

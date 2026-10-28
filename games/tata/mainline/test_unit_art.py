"""Regression for the packed vertex mapping (zero is the hidden column)."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

try:
    import numpy as np
    from PIL import Image
    from render_unit_art import idle_pose,rasterize
    AVAILABLE=True
except ImportError:
    AVAILABLE=False


@unittest.skipUnless(AVAILABLE,'Optional art extraction dependencies required')
class IdleArtTests(unittest.TestCase):
    def test_index_mapping_and_packed_alpha(self):
        handler=SimpleNamespace(process=lambda:None,m_UV0=[(.1,.1)]*5,
            m_UV1=[(i,0) for i in range(5)])
        xy=np.array([[0,0],[-.5,0],[.5,0],[.5,1],[-.5,1]])
        positions=np.ones((1,5,4),dtype='<f2')*.5
        positions[0,:,:2]=(xy+1)/2
        position=SimpleNamespace(m_TextureFormat=17,m_Height=1,m_Width=5,image_data=positions.tobytes())
        color=SimpleNamespace(m_TextureFormat=63,m_Height=1,m_Width=5,image_data=bytes([0,15,15,15,15]))
        indexes=SimpleNamespace(m_TextureFormat=3,m_Height=1,m_Width=5,
            image_data=bytes([1,0,0,2,0,0,3,0,0,4,0,0,0,0,0]))
        with patch('render_unit_art.MeshHandler',return_value=handler):
            got,alpha=idle_pose(None,position,color,indexes,dict(startFrame=0,isTextureGroup0=1),0,-1,1)
        np.testing.assert_allclose(got[:4],xy[1:])
        np.testing.assert_allclose(alpha,[1,1,1,1,0])

    def test_uv_quad_rasterization(self):
        handler=SimpleNamespace(process=lambda:None,m_Vertices=[(0,0,0),(1,0,0),(1,1,0),(0,1,0)],
            m_UV0=[(0,0),(1,0),(1,1),(0,1)],get_triangles=lambda:[[(0,1,2),(0,2,3)]])
        with patch('render_unit_art.MeshHandler',return_value=handler):
            image=rasterize(None,Image.new('RGBA',(8,8),(230,50,30,255)),size=64)
        self.assertGreater(image.width,30)
        self.assertEqual(image.getpixel((image.width//2,image.height//2)),(230,50,30,255))


if __name__=='__main__':unittest.main()

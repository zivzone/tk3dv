import sys, os, argparse, cv2, glob, math, random
FileDirPath = os.path.dirname(os.path.realpath(__file__))
from tk3dv import pyEasel
from PyQt5.QtWidgets import QApplication
import PyQt5.QtCore as QtCore
from PyQt5.QtGui import QKeyEvent, QMouseEvent, QWheelEvent

from EaselModule import EaselModule
from Easel import Easel
import numpy as np
import OpenGL.GL as gl
from tk3dv.nocstools import datastructures as ds

from palettable.tableau import Tableau_20, BlueRed_12, ColorBlind_10, GreenOrange_12
from palettable.cartocolors.diverging import Earth_2
import calibration
from tk3dv.common import drawing

class NOCSMapModule(EaselModule):
    def __init__(self):
        super().__init__()

    def init(self, InputArgs=None):
        self.Parser = argparse.ArgumentParser(description='NOCSMapModule to visualize NOCS maps and camera poses.', fromfile_prefix_chars='@')
        ArgGroup = self.Parser.add_argument_group()
        ArgGroup.add_argument('--nocs-maps', nargs='+', help='Specify input NOCS maps. * globbing is supported.', required=True)
        ArgGroup.add_argument('--colors', nargs='+', help='Specify RGB images corresponding to the input NOCS maps. * globbing is supported.', required=False)
        ArgGroup.add_argument('--intrinsics', help='Specify the intrinsics file to estimate camera pose.', required=False, default=None)
        ArgGroup.add_argument('--no-pose', help='Choose to not estimate pose.',
                              action='store_true')
        self.Parser.set_defaults(no_pose=False)

        self.Args, _ = self.Parser.parse_known_args(InputArgs)
        if len(sys.argv) <= 1:
            self.Parser.print_help()
            exit()

        self.NOCSMaps = []
        self.NOCS = []
        self.CamRots = []
        self.CamPos = []
        self.CamIntrinsics = []
        self.CamFlip = [] # This is a hack
        self.PointSize = 3
        self.Intrinsics = None
        if self.Args.intrinsics is not None:
            self.Intrinsics = ds.CameraIntrinsics()
            self.Intrinsics.init_with_file(self.Args.intrinsics)
            self.ImageSize = (self.Intrinsics.Width, self.Intrinsics.Height)
        if self.Intrinsics is None:
            self.ImageSize = (640, 480)
            print('[ WARN ]: No intrinsics provided. Resizing and padding image to', self.ImageSize)

        self.nNM = 0
        self.SSCtr = 0
        self.takeSS = False
        self.showNOCS = True
        self.showBB = True
        self.loadData()

    def drawNOCS(self, lineWidth=2.0, ScaleX=1, ScaleY=1, ScaleZ=1, OffsetX=0, OffsetY=0, OffsetZ=0):
        gl.glPushMatrix()

        gl.glScale(ScaleX, ScaleY, ScaleZ)
        gl.glTranslate(OffsetX, OffsetY, OffsetZ)  # Center on cube center
        drawing.drawUnitCube(lineWidth, True)

        gl.glPopMatrix()

    @staticmethod
    def estimateCameraPoseFromNM(NOCSMap, NOCS, N=None, Intrinsics=None):
        ValidIdx = np.where(np.all(NOCSMap != [255, 255, 255], axis=-1)) # row, col

        # Create correspondences tuple list
        x = np.array([ValidIdx[1], ValidIdx[0]]) # row, col ==> u, v
        # Convert image coordinates from top left to bottom right (See Figure 6.2 in HZ)
        x[0, :] = NOCSMap.shape[1] - x[0, :]
        x[1, :] = NOCSMap.shape[0] - x[1, :]

        X = NOCS.Points.T

        # Enough to do pose estimation from a subset of points but randomly distributed in the image
        MaxN = x.shape[1]
        if N is not None:
            MaxN = min(N, x.shape[1])
        RandIdx = [i for i in range(0, x.shape[1])]
        random.shuffle(RandIdx)
        RandIdx = RandIdx[:MaxN]
        x = x[:, RandIdx]
        X = X[:, RandIdx]

        Corr = []
        for i in range(0, max(X.shape)):
            Corr.append((x[:, i], X[:, i]))

        p, c, k, r, Flip = calibration.calculateCameraParameters(Corr)

        print('Full estimate:\n')
        print('R:\n', r, '\n')
        print('C:\n', c, '\n')
        print('K:\n', k, '\n\n')

        useEstimatedK = True
        if useEstimatedK == False and Intrinsics is not None:
            # Use passed K to refine r, c
            rc = np.linalg.inv(Intrinsics.Matrix) @ p
            r = rc[:, :-1]
            c = -r.T @ rc[:, -1]
            k = Intrinsics.Matrix

        print('K-based estimate:\n')
        print('R:\n', r, '\n')
        print('C:\n', c, '\n')
        print('K:\n', k, '\n\n')

        return p, k, r, c, Flip

    @staticmethod
    def getFileNames(InputList):
        FileNames = []
        for File in InputList:
            if '*' in File:
                GlobFiles = glob.glob(File, recursive=False)
                GlobFiles.sort()
                FileNames.extend(GlobFiles)
            else:
                FileNames.append(File)

        return FileNames

    def resizeAndPad(self, Image):
        # SquareUpSize = min(self.ImageSize[0], self.ImageSize[1])
        # TODO
        Image = cv2.resize(Image, self.ImageSize, interpolation=cv2.INTER_NEAREST)

        return Image

    def loadData(self):
        Palette = ColorBlind_10
        NMFiles = self.getFileNames(self.Args.nocs_maps)
        ColorFiles = [None] * len(NMFiles)
        if self.Args.colors is not None:
            ColorFiles = self.getFileNames(self.Args.colors)

        for (NMF, Color, CF) in zip(NMFiles, Palette.colors, ColorFiles):
            NOCSMap = cv2.imread(NMF, -1)
            NOCSMap = NOCSMap[:, :, :3] # Ignore alpha if present
            NOCSMap = cv2.cvtColor(NOCSMap, cv2.COLOR_BGR2RGB) # IMPORTANT: OpenCV loads as BGR, so convert to RGB
            NOCSMap = self.resizeAndPad(NOCSMap)
            CFIm = None
            if CF is not None:
                CFIm = cv2.imread(CF)
                CFIm = cv2.cvtColor(CFIm, cv2.COLOR_BGR2RGB) # IMPORTANT: OpenCV loads as BGR, so convert to RGB
                CFIm = cv2.resize(CFIm, self.ImageSize, interpolation=cv2.INTER_NEAREST)
            NOCS = ds.NOCSMap3D(NOCSMap, RGB=CFIm)
            NOCS.update()
            self.NOCSMaps.append(NOCSMap)
            self.NOCS.append(NOCS)

            if self.Args.no_pose == False:
                _, K, R, C, Flip = self.estimateCameraPoseFromNM(NOCSMap, NOCS, N=1000, Intrinsics=self.Intrinsics) # The rotation and translation are about the NOCS origin
                self.CamIntrinsics.append(K)
                self.CamRots.append(R)
                self.CamPos.append(C)
                self.CamFlip.append(Flip)

        self.nNM = len(NMFiles)
        self.activeNMIdx = self.nNM # len(NMFiles) will show all

    def step(self):
        pass

    def draw(self):
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glPushMatrix()

        ScaleFact = 500
        gl.glTranslate(-ScaleFact/2, -ScaleFact/2, -ScaleFact/2)
        gl.glScale(ScaleFact, ScaleFact, ScaleFact)
        for Idx, NOCS in enumerate(self.NOCS):
            if self.activeNMIdx != self.nNM:
                if Idx != self.activeNMIdx:
                    continue
            NOCS.draw(self.PointSize)
            if self.showBB:
                NOCS.drawBB()

        for Idx, (K, R, C, isF) in enumerate(zip(self.CamIntrinsics, self.CamRots, self.CamPos, self.CamFlip), 0):
            if self.activeNMIdx != self.nNM:
                if Idx != self.activeNMIdx:
                    continue

            gl.glPushMatrix()

            ScaleRotMat = np.identity(4)
            ScaleRotMat[:3, :3] = R

            gl.glTranslate(C[0], C[1], C[2])
            gl.glMultMatrixf(ScaleRotMat)
            if isF:
                gl.glRotate(180, 1, 0, 0)

            drawing.drawAxes(0.2)
            gl.glPopMatrix()

        if self.showNOCS:
            self.drawNOCS(lineWidth=5.0)

        gl.glPopMatrix()

        if self.takeSS:
            x, y, width, height = gl.glGetIntegerv(gl.GL_VIEWPORT)
            # print("Screenshot viewport:", x, y, width, height)
            gl.glPixelStorei(gl.GL_PACK_ALIGNMENT, 1)

            data = gl.glReadPixels(x, y, width, height, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
            SS = np.frombuffer(data, dtype=np.uint8)
            SS = np.reshape(SS, (height, width, 3))
            SS = cv2.flip(SS, 0)
            SS = cv2.cvtColor(SS, cv2.COLOR_BGR2RGB)
            cv2.imwrite('screenshot_' + str(self.SSCtr).zfill(6) + '.png', SS)
            self.SSCtr = self.SSCtr + 1
            self.takeSS = False

    def keyPressEvent(self, a0: QKeyEvent):
        if a0.key() == QtCore.Qt.Key_Plus:  # Increase or decrease point size
            if self.PointSize < 20:
                self.PointSize = self.PointSize + 1

        if a0.key() == QtCore.Qt.Key_Minus:  # Increase or decrease point size
            if self.PointSize > 1:
                self.PointSize = self.PointSize - 1

        if a0.key() == QtCore.Qt.Key_T:  # Toggle NOCS views
            if self.nNM > 0:
                self.activeNMIdx = (self.activeNMIdx + 1)%(self.nNM+1)

        if a0.key() == QtCore.Qt.Key_N:
            self.showNOCS = not self.showNOCS
        if a0.key() == QtCore.Qt.Key_B:
            self.showBB = not self.showBB

        if a0.key() == QtCore.Qt.Key_S:
            print('[ INFO ]: Taking snapshot.')
            self.takeSS = True


if __name__ == '__main__':
    app = QApplication(sys.argv)

    mainWindow = Easel([NOCSMapModule()], sys.argv[1:])
    mainWindow.show()
    sys.exit(app.exec_())
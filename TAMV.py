#!/usr/bin/env python3

# Python Script to align multiple tools on Jubilee printer with Duet3d Controller
# Using images from USB camera and finding circles in those images
#
# Copyright (C) 2020 Danal Estes all rights reserved.
# Released under The MIT License. Full text available via https://opensource.org/licenses/MIT
#
# Requires OpenCV to be installed on Pi
# Requires running via the OpenCV installed python (that is why no shebang)
# Requires network connection to Duet based printer running Duet/RepRap V2 or V3
#

import os
import sys
import imutils
import datetime
import time
import numpy as np
import argparse
import math
import csv
import threading

# set resolution for webcam capture
global resolutionWidth, resolutionHeight
resolutionWidth = 640
resolutionHeight = 480

# load DuetWebAPI
try: 
    import DuetWebAPI as DWA
except ImportError:
    print("Python Library Module 'DuetWebAPI.py' is required. ")
    print("Obtain from https://github.com/DanalEstes/DuetWebAPI ")
    print("Place in same directory as script, or in Python libpath.")
    exit(8)

# Check if running in a graphics console
if (os.environ.get('SSH_CLIENT')):
    print("This script MUST run on the graphics console, not an SSH session.")
    exit(8)

# load OpenCV libraries
print("Startup may take a few moments: loading openCV libraries; some of them are very large..")
try:
    global cv2
    import cv2
    print( "openCV ("+cv2.__version__+") libraries have been loaded.")
    print('')
except:
    print("Import for CV2 failed.  Please install openCV")
    print("You may wish to use https://github.com/DanalEstes/PiInstallOpenCV")
    print("Or you could even try a sudo apt install python3-opencv")
    print('')
    exit(8)

# threaded video frame get class
class VideoGet:
    """
    Class that continuously gets frames from a VideoCapture object
    with a dedicated thread.
    """

    def __init__(self, src=0):
        self.stream = cv2.VideoCapture(src)
        self.stream.set(cv2.CAP_PROP_FRAME_WIDTH, resolutionWidth)
        self.stream.set(cv2.CAP_PROP_FRAME_HEIGHT, resolutionHeight)
        self.stream.set(cv2.CAP_PROP_BUFFERSIZE,1)
        self.stream.set(cv2.CAP_PROP_FPS,25)        
        (self.grabbed, self.frame) = self.stream.read()
        self.stopped = False
        
    def start(self):    
        #Thread(target=self.get, args=()).start()
        return self

    def get(self):
        while not self.stopped:
            if not self.grabbed:
                self.stop()
            else:
                (garbagegrabbed, garbageframe) = self.stream.read()
                #(garbagegrabbed, garbageframe) = self.stream.read()
                (self.grabbed, self.frame) = self.stream.read()

    def stop(self):
        self.stopped = True
        self.stream.release()

# threaded video frame show class
class VideoShow:
    """
    Class that continuously shows a frame using a dedicated thread.
    """

    def __init__(self, frame=None):
        self.frame = frame
        self.stopped = False
        self.text = "Welcome to TAMV"
        
    def start(self):
        #Thread(target=self.show, args=()).start()
        return self

    def show(self,title="TAMV"):
        while not self.stopped:
            #cv2.namedWindow("TAMV",cv2.WINDOW_NORMAL)
            cv2.imshow("TAMV", self.frame)
            cv2.displayOverlay("TAMV",self.text )
            if cv2.waitKey(1) == ord("q"):
                self.stopped = True
            
                
    def overlay(self,text):
        cv2.displayOverlay("TAMV",text )

    def stop(self):
        self.stopped = True 

def callbackButton():
    return
###################################################################################
# Start of methods 
###################################################################################
def init():
    os.environ['QT_LOGGING_RULES'] ="qt5ct.debug=false"
    # parse command line arguments
    parser = argparse.ArgumentParser(description='Program to allign multiple tools on Duet based printers, using machine vision.', allow_abbrev=False)
    parser.add_argument('-duet',type=str,nargs=1,default=['localhost'],help='Name or IP address of Duet printer. You can use -duet=localhost if you are on the embedded Pi on a Duet3.')
    parser.add_argument('-vidonly',action='store_true',help='Open video window and do nothing else.')
    parser.add_argument('-camera',type=int,nargs=1,default=[0],help='Index of /dev/videoN device to be used.  Default 0. ')
    parser.add_argument('-cp',type=float,nargs=2,default=[-999,-999],help="x y that will put 'controlled point' on carriage over camera.")
    parser.add_argument('-repeat',type=int,nargs=1,default=[1],help="Repeat entire alignment N times and report statistics")
    parser.add_argument('-xray',action='store_true',help='Display edge detection output for troubleshooting.')
    parser.add_argument('-loose',action='store_true',help='Run circle detection algorithm with less stringent parameters to help detect worn nozzles.')
    parser.add_argument('-export',action='store_true',help='Export repeat raw data to output.csv when done.')
    parser.add_argument('-alternate',action='store_true',help='Try alternative nozzle detection method')
    parser.add_argument('-speedy',action='store_true',help='Set travel moves to 200mm/s at 2000mm/s2 acceleration')
    args=vars(parser.parse_args())

    global duet, vidonly, camera, cp, repeat, xray, loose, export, alternate, speedy
    duet      = args['duet'][0]
    vidonly   = args['vidonly']
    camera    = args['camera'][0]
    cp        = args['cp']
    repeat    = args['repeat'][0]
    xray      = args['xray']
    loose     = args['loose']
    export    = args['export']
    alternate = args['alternate']
    speedy    = args['speedy']

    # Get connected to the printer.
    print('Attempting to connect to printer at '+duet)
    global printer
    printer = DWA.DuetWebAPI('http://'+duet)
    if (not printer.printerType()):
        print('Device at '+duet+' either did not respond or is not a Duet V2 or V3 printer.')
        print('')
        exit(2)
    printer = DWA.DuetWebAPI('http://'+duet)
    print("Connected to a Duet V"+str(printer.printerType())+" printer at "+printer.baseURL())
    print('')
    if not vidonly:
        print('')
        print('#########################################################################')
        print('# Important:                                                            #')
        print('# Your printer MUST be capable of mounting and parking every tool with  #')
        print('# no collisions between tools.                                          #')
        print('#                                                                       #')
        print('# Offsets for each tool must be set roughly correctly, even before the  #')
        print('# first run of TAMV.  They do not need to be perfect; only good enough  #')
        print('# to get the tool on camera.  TAMV has to see it to align it.           #')
        print('#########################################################################')
        print('')
        '''print('#########################################################################')
        print('# Hints:                                                                #')
        print('# Preferred location for the camera is along the max Y edge of the bed. #')
        print('# Fixed camera is also OK, but may limit aligning tools that differ     #')
        print('# significantly in Z.                                                   #')
        print('#                                                                       #')
        print('# If circle detect finds no circles, try changing lighting, changing z, #')
        print('# cleaning the nozzle, or slightly blurring focus.                      #')
        print('#                                                                       #')
        print('# Quite often, the open end of the insulation on the heater wires will  #')
        print('# be detected as a circle.  They may have to be covered.                #')
        print('#                                                                       #')
        print('# Your "controlled point" can be anything. Tool changer pin is fine.    #')
        print('#########################################################################')
        print('')'''
    return

def find_theta(x,y,x_o,y_o):
  return math.asin((x*y_o-y*x_o)/(x**2+y**2))

def rotate_points(matrix, points):
  x = points[0]*matrix[0][0]+points[1]*matrix[0][1]
  y = points[0]*matrix[1][0]+points[1]*matrix[1][1]
  return (x,y)

def getRotationMatrix( theta ):
    return ([ [math.cos(theta), -1*math.sin(theta)], [math.sin(theta), math.cos(theta)]] )

#Convert the camera coordinates from pixels to machine distances
def convert_coords(camera_coords, pixel_dist, rotation_matrix):
  x,y = camera_coords
  x,y = rotate_points(rotation_matrix, [x,y])
  x,y = (x/pixel_dist, y/pixel_dist)
  return x,y

# display video window alone
def vidWindow(vidGetter, vidShower):
    print('')
    print('Video Window only selected with -vidonly')
    print('Press Ctrl+C to exit.')
    # jog print head if cp flag was initialized
    if( cp[0] != -999 and cp[1] != -999 ):
        printer.gCode("G1 F3000 X" + str(cp[0]) + " Y" + str(cp[1]))
    rotation = 0
    try:
        while True:
            (xy, target, rotation, tempCoordinates, radius) = runVideoStream(vidGetter,vidShower, rotation)
            vidShower.text = "(X,Y): ({0:3.3f}, {1:3.3f}) / (U,V,R): ({2:3.0f}, {3:3.0f}, {4:2.0f})".format(tempCoordinates['X'],tempCoordinates['Y'],xy[0],xy[1],radius)
            continue
    except KeyboardInterrupt:
        print( 'Exiting after parking tools.' )
        #printer.gCode("T-1 ")
        return
    except Exception as cpe1:
        print( 'Unknown error.' )
        print( cpe1 )
        printer.gCode("T-1")
        return


# function to convert image from RGB to YCrCb and equalize Y channel (enhance low light image)
def hisEqulColor(img):
    ycrcb=cv2.cvtColor(img,cv2.COLOR_BGR2YCR_CB)
    channels=cv2.split(ycrcb)
    cv2.equalizeHist(channels[0],channels[0])
    cv2.merge(channels,ycrcb)
    returnImage = cv2.cvtColor(ycrcb,cv2.COLOR_YCR_CB2BGR)
    return returnImage

# Noise reduction enhancement via averaging 5 frames for noise detection  + low light compensation
def noiseEnhance( images = [] ):
    average = images[0]
    for image in images[1:]:
        average += image
    average /= (len( images ))
    return average
    #average = hisEqulColor(average)

# blob detector parameters and setup
def createDetector(t1=1,t2=50, all=0.5, area=250):
    # Setup SimpleBlobDetector parameters.
    params = cv2.SimpleBlobDetector_Params()
    params.minThreshold = t1          # Change thresholds
    params.maxThreshold = t2
    params.thresholdStep = 1
    params.filterByArea = True         # Filter by Area.
    params.minArea = area
    params.filterByCircularity = True  # Filter by Circularity
    if( loose ):
        # more relaxed parameters for circle detection
        params.minCircularity = 0.2
    else:
        params.minCircularity = 0.8
    params.maxCircularity= 1
    params.filterByConvexity = True    # Filter by Convexity
    params.minConvexity = 0.8
    params.maxConvexity = 1
    params.filterByInertia = True      # Filter by Inertia
    params.minInertiaRatio = 0.8
    detector = cv2.SimpleBlobDetector_create(params)
    return(detector)

# calculate distances for 2 vectors
def vectDist(xy1,xy2):
    # Final rounding and int() because we are really calculating pixels here. 
    # Probably some of these 'float()' casts are overkill; still, better to be explicit. 
    return int(np.around(np.sqrt(abs( \
        (float(xy2[0]) - float(xy1[0])) ** float(2) + \
        (float(xy2[1]) - float(xy1[1])) ** float(2)   \
        ))))

# display keypoints on frame
def printKeypointXYR(keypoints):
    for i in range(len(keypoints)):
        print("Keypoint "+str(i)+" XY = ",np.around(keypoints[i].pt,3))
        print("Keypoints "+str(i)+" R = ",np.around(keypoints[i].size/2,3))

def controlledPoint(get,show):
    printer.gCode("T-1 ")   # Un Mount any/all tools
    # Get user to position the first tool over the camera.
    print('')
    print('Setting up controlled point for offset calculation')
    print('#########################################################################')
    print('# We recommend setting up the center of your Z probe in the frame.      #')
    print('# 1) Using Duet Web, jog until your controlled point appears.           #')
    print('# 2) Using Duet Web, very roughly center the controled point            #')
    print('# 3) Click back in this script window, and press Ctrl+C                 #')
    print('#########################################################################')
    try:
        while True:
            if (get.stopped or show.stopped):
                #show.stop()
                #get.stop()
                break
            nowframe = get.frame
            nowframe = cv2.circle(nowframe, (int(get.stream.get(cv2.CAP_PROP_FRAME_WIDTH)/2),int(get.stream.get(cv2.CAP_PROP_FRAME_HEIGHT)/2)),int(get.stream.get(cv2.CAP_PROP_FRAME_WIDTH)/6), (0,255,0),2 )
            nowframe = cv2.circle(nowframe, (int(get.stream.get(cv2.CAP_PROP_FRAME_WIDTH)/2),int(get.stream.get(cv2.CAP_PROP_FRAME_HEIGHT)/2)),6, (0,0,255),1 )
            show.frame = nowframe
        return (get, show)  
            
    except KeyboardInterrupt:
        print('')
        print("Capturing raw position of the control point.")
        CPCoords = printer.getCoords()
        print("Controlled Point X{0:-1.3f} Y{1:-1.3f} ".format(CPCoords['X'],CPCoords['Y']))
        print('')
        return (get, show, CPCoords)
    except:
        raise
    
def getDistance( x1, y1, x0, y0 ):
    x1_float = float(x1)
    x0_float = float(x0)
    y1_float = float(y1)
    y0_float = float(y0)
    x_dist = (x1_float - x0_float) ** 2
    y_dist = (y1_float - y0_float) ** 2
    retVal = np.sqrt((x_dist + y_dist))
    return np.around(retVal,3)

def normalize_coords(coords):
    xdim, ydim = resolutionWidth, resolutionHeight
    return (coords[0] / xdim - 0.5, coords[1] / ydim - 0.5)

def least_square_mapping(calibration_points):
    """Compute a 2x2 map from displacement vectors in screen space
    to real space. """
    n = len(calibration_points)
    real_coords, pixel_coords = np.empty((n,2)),np.empty((n,2))
    for i, (r,p) in enumerate(calibration_points):
        real_coords[i] = r
        pixel_coords[i] = p
        
    x,y = pixel_coords[:,0],pixel_coords[:,1]
    A = np.vstack([x**2,y**2,x * y, x,y,np.ones(n)]).T
    transform = np.linalg.lstsq(A, real_coords, rcond = None)
    return transform[0], transform[1].mean()

def eachTool(tool, rep, get, show, CPCoords, transMatrix=None, mpp=0):
    toolStartTime = time.time()
    
    avg=[0,0]
    location = {'X':0,'Y':0}
    guess  = [1,1]  # Millimeters.
    xy     = [0,0]
    oldxy  = xy
    state = 0 # State machine for figuring out image rotation to carriage XY move mapping.
    rotation = 0 # Amount of rotation of image.
    count=0
    machine_coordinates = CPCoords
    iterations = 10
    calibrationCoordinates = [
        [0,-0.5],
        [0.294,-0.405],
        [0.476,-0.155],
        [0.476,0.155],
        [0.294,0.405],
        [0,0.5],
        [-0.294,0.405],
        [-0.476,0.155],
        [-0.476,-0.155],
        [-0.294,-0.405],
        ]
    # transofrmation matrix already calculated and passed as parameter, jump straight to nozzle alignemnt
    if( transMatrix is not None ):
        transform = transMatrix
        state = 200

    print('')
    print("Mounting tool T{0:d} for repeat pass {1:d}. ".format(tool,rep+1))
    show.text = "Mounting tool T{0:d} for repeat pass {1:d}. ".format(tool,rep+1)
    print('')
    printer.gCode("T{0:d} ".format(tool))           # Mount correct tool
    printer.gCode("M400")
    if speedy:
        printer.gCode("G1 F13200 Y{0:1.3f} ".format(np.around(CPCoords['Y'],3)))     # Position Tool in Frame
        printer.gCode("G4 P500")
        printer.gCode("G1 F13200 X{0:1.3f} ".format(np.around(CPCoords['X'],3)))     # X move first to avoid hitting parked tools.
    else:
        printer.gCode("G1 F5000 Y{0:1.3f} G4 P500 G1 F5000 X{1:1.3f}".format(np.around(CPCoords['Y'],3),np.around(CPCoords['X'],3) ))     # Position Tool in Frame
        #printer.gCode("G4 P500")
        #printer.gCode("G1 F5000 X{0:1.3f} ".format(np.around(CPCoords['X'],3)))     # X move first to avoid hitting parked tools. 
    #printer.gCode("M400")
    print('Waiting for machine to position itself at controlled point..' )
    print('')
    if(tool == 0 and rep == 0):
        print('#########################################################################')
        print('# If tool does not appear in window, adjust G10 Tool offsets to be      #')
        print('# roughly correct.  Then re-run TAMV from the beginning.                #')
        print('#                                                                       #')
        print('# If no circles are found, try slight jogs in Z, changing lighting,     #')
        print('# and cleaning the nozzle.                                              #')
        print('#########################################################################')
        print('')
    # loop over the frames from the video stream
    spaceCoords = []
    cameraCoords = []
    movesCounter = 0
    
    while True:
        #printer.gCode("M400")
        if printer.getStatus() in 'idle':
            (xy, target, rotation, machineCoordinates, radius) = runVideoStream(get,show, rotation)
            # Found one and only one circle.  Process it.

            # Keep track of center of circle and average across many circles
            avg[0] += xy[0]
            avg[1] += xy[1]
            count += 1
            
            if (count > 14 ):
                avg[0] /= count
                avg[1] /= count
                avg = np.around(avg,3)
                # refresh positional variables to debounce movements
                (xy, target, rotation, machineCoordinates, radius) = runVideoStream(get,show, rotation)
                show.text = "(X,Y): ({0:3.3f}, {1:3.3f}) / (U,V,R): ({2:3.0f}, {3:3.0f}, {4:2.0f})".format(machineCoordinates['X'],machineCoordinates['Y'],xy[0],xy[1],radius)
                if (state == 0):  
                    # Finding Rotation: Collected frames before first move.
                    # Adjust jerk and movement parameters for a smoother calibration
                    # HBHBHB printer.gCode("M566 X300 Y300 Z50")
                    # HBHBHB printer.gCode("M201 X1000 Y1000")
                    print("Calibrating camera step 1/2: Determining camera transformation matrix by measuring 10 random positions.")
                    show.text = "Calibrating camera rotation: {}% done".format(int(state*10))
                    oldxy = xy
                    spaceCoords = []
                    cameraCoords = []
                    spaceCoords.append( (machineCoordinates['X'],machineCoordinates['Y']) )
                    cameraCoords.append((xy[0],xy[1]))
                    # move carriage +1 in X
                    print('\r{}% done...'.format(int(state*10)), end='', flush=True)
                    offsetX = calibrationCoordinates[0][0]
                    offsetY = calibrationCoordinates[0][1]
                    printer.gCode("G91 G1 X" + str(offsetX) + " Y" + str(offsetY) +" F3000 G90 ")
                    state = 1
                    continue
                elif( state >= 1 and state < iterations):
                    print('\r{}% done...'.format(int(state*10)), end='', flush=True)
                    show.text = "Calibrating camera rotation: {}% done".format(int(state*10))
                    if( state == 1 ):
                        mpp = np.around(0.5/getDistance(oldxy[0],oldxy[1],xy[0],xy[1]),4)
                    oldxy = xy
                    spaceCoords.append( (machineCoordinates['X'],machineCoordinates['Y']) )
                    cameraCoords.append((xy[0],xy[1]))
                    # return carriage to relative center of movement
                    offsetX = -1*offsetX
                    offsetY = -1*offsetY
                    printer.gCode("G91 G1 X" + str(offsetX) + " Y" + str(offsetY) +" F3000 G90 ")
                    # move carriage a random amount in X&Y to collect datapoints for transform matrix
                    offsetX = calibrationCoordinates[state][0]
                    offsetY = calibrationCoordinates[state][1]
                    printer.gCode("G91 G1 X" + str(offsetX) + " Y" + str(offsetY) +" F3000 G90 ")
                    state += 1
                    continue
                elif( state == iterations ):
                    print('\r{}% done...'.format(int(state*10)))
                    show.text = "Calibrating camera rotation: {}% done".format(int(state*10))
                    print('')
                    print('mm per pixel calulcated: ' + str(mpp))
                    print("Camera calibration completed, now calibrating nozzle offsets..")
                    show.text = "Camera calibration done. mm per pixel = {0:0.4f}".format(mpp)
                    oldxy = xy
                    spaceCoords.append( (machineCoordinates['X'],machineCoordinates['Y']) )
                    cameraCoords.append((xy[0],xy[1]))
                    transform_input = [(spaceCoords[i], normalize_coords(camera)) for i, camera in enumerate(cameraCoords)]
                    transform, residual = least_square_mapping(transform_input)
                    newCenter = transform.T @ np.array([0, 0, 0, 0, 0, 1])
                    guess[0]= np.around(newCenter[0],3)
                    guess[1]= np.around(newCenter[1],3)
                    printer.gCode("G90 G1 X{0:-1.3f} Y{1:-1.3f} F1000 G90 ".format(guess[0],guess[1]))
                    # reset printer jerk and acceleration
                    printer.resetAdvancedMovement()
                    #printer.gCode("M400")
                    state = 200
                    continue
                elif (state == 200):
                    print('\r Nozzle move #{}...'.format(int(movesCounter)), end='', flush=True)
                    show.text = "Nozzle move #{}".format(int(movesCounter))
                    movesCounter += 1
                    # nozzle detected, frame rotation is set, start
                    cx,cy = normalize_coords(xy)
                    v = [cx**2, cy**2, cx*cy, cx, cy, 0]
                    offsets = -1*(0.55*transform.T @ v)
                    offsets[0] = np.around(offsets[0],3)
                    offsets[1] = np.around(offsets[1],3)
                    
                    # Move it a bit
                    printer.gCode( "M564 S1" )
                    if speedy:
                        printer.gCode("M204 P2000 T2000 G91 G1 X{0:-1.3f} Y{1:-1.3f} F13200 G90 ".format(offsets[0],offsets[1]))
                    else:
                        printer.gCode("G91 G1 X{0:-1.3f} Y{1:-1.3f} F1000 G90 ".format(offsets[0],offsets[1]))
                    #printer.gCode("M400")
                    oldxy = xy
                    if ( offsets[0] == 0.0 and offsets[1] == 0.0 ):
                        # Process coordinates for offset calculations
                        print('\r Nozzle move #{}...'.format(int(movesCounter-1)))
                        print('')
                        #printer.gCode("M400")
                        c=machineCoordinates
                        c['MPP'] = mpp
                        c['time'] = time.time() - toolStartTime
                        print("Found Center of Image at offset coordinates X"+str(c['X'])+' Y'+str(c['Y']))
                        show.text="Found offset: X"+str(c['X'])+' Y'+str(c['Y'])+" / mm per pixel = {0:0.4f}".format(mpp)
                        return(c, transform, mpp)
                    else:
                        state = 200
                        continue
                avg = [0,0]
                location = {'X':0,'Y':0}
                count = 0

def repeatReport(toolCoordsInput,repeatInput=1):
    ###################################################################################
    # Report on repeated executions
    ###################################################################################
    print('')
    print('Repeatability statistics for '+str(repeatInput)+' repeats:')
    print('+---------------------------------------------------------------------------------------------------------------------------+')
    print('|   |                             X                             |                        Y                        |  Time   |')
    print('| T |   MPP   |   Avg   |   Max   |   Min   |  StdDev |  Range  |   Avg   |   Max   |   Min   |  StdDev |  Range  | Seconds |')
    for t in range(printer.getNumTools()):
        #  | 0 |   123   | 123.456 | 123.456 | 123.456 | 123.456 | 123.456 | 123.456 | 123.456 | 123.456 | 123.456 | 123.456 | 123.456 |
        xrange = np.around(np.max([toolCoordsInput[i][t]['X'] for i in range(repeatInput)]),3) - np.around(np.min([toolCoordsInput[i][t]['X'] for i in range(repeatInput)]),3)
        yrange = np.around(np.max([toolCoordsInput[i][t]['Y'] for i in range(repeatInput)]),3) - np.around(np.min([toolCoordsInput[i][t]['Y'] for i in range(repeatInput)]),3)
        print('| {0:1.0f} '.format(t),end='')
        print('| {0:6.3f}  '.format(np.around(np.average([toolCoordsInput[i][t]['MPP'] for i in range(repeatInput)]),3)),end='')
        print('| {0:7.3f} '.format(np.around(np.average([toolCoordsInput[i][t]['X'] for i in range(repeatInput)]),3)),end='')
        print('| {0:7.3f} '.format(np.around(np.max([toolCoordsInput[i][t]['X'] for i in range(repeatInput)]),3)),end='')
        print('| {0:7.3f} '.format(np.around(np.min([toolCoordsInput[i][t]['X'] for i in range(repeatInput)]),3)),end='')
        print('| {0:6.3f}  '.format(np.around(np.std([toolCoordsInput[i][t]['X'] for i in range(repeatInput)]),3)),end='')
        print('| {0:6.3f}  '.format(xrange),end='')
        print('| {0:7.3f} '.format(np.around(np.average([toolCoordsInput[i][t]['Y'] for i in range(repeatInput)]),3)),end='')
        print('| {0:7.3f} '.format(np.around(np.max([toolCoordsInput[i][t]['Y'] for i in range(repeatInput)]),3)),end='')
        print('| {0:7.3f} '.format(np.around(np.min([toolCoordsInput[i][t]['Y'] for i in range(repeatInput)]),3)),end='')
        print('| {0:6.3f}  '.format(np.around(np.std([toolCoordsInput[i][t]['Y'] for i in range(repeatInput)]),3)),end='')
        print('| {0:6.3f}  '.format(yrange),end='')
        print('| {0:7.3f} '.format(np.around(np.average([toolCoordsInput[i][t]['time'] for i in range(repeatInput)]),3)),end='|')
        print('')
    print('+---------------------------------------------------------------------------------------------------------------------------+')
    print('Note: Repeatability cannot be better than one pixel, see Millimeters per Pixel, above.')
    # HBHBHB TODO: Add option for export if not selected at command line call
    if( export ):
        try:
            fileData = "{\"tools\":["
            for tool in range(printer.getNumTools()):
                fileData += "{\"toolNumber\":\""+str(tool)+"\","
                fileData += "\"runs\":["
                for run in range(repeatInput):
                    fileData += "{\"run\":\""+str(run)+"\","
                    fileData += "\"X\":\"" + str(toolCoordsInput[run][tool]['X']) + "\","
                    fileData += "\"Y\":\"" + str(toolCoordsInput[run][tool]['Y']) + "\","
                    fileData += "\"MPP\":\"" + str(toolCoordsInput[run][tool]['MPP']) + "\""
                    if run == repeatInput-1: fileData += "}]"
                    else: fileData += "},"
                if tool == printer.getNumTools()-1: fileData += "}]"
                else: fileData += "},"
            fileData += "}"
            with open("output.json","w") as text_file:
                print(fileData, file=text_file)
        except OSError:
            print( 'ERROR: Cannot create data export file!')
            return

def adjust_gamma(image, gamma=1.2):
    # build a lookup table mapping the pixel values [0, 255] to
    # their adjusted gamma values
    invGamma = 1.0 / gamma
    table = np.array([((i / 255.0) ** invGamma) * 255
        for i in np.arange(0, 256)]).astype("uint8")
    # apply gamma correction using the lookup table
    return cv2.LUT(image, table)

###################################################################################
# This method runs in a separate thread, to own the camera, 
# present video stream to X11 window, 
# perform machine vision circle recognition, and more.
###################################################################################
def runVideoStream(get, show, rotationInput):
    xy     = [0,0]
    rd = int(round(time.time()*1000))
    nocircle = 0    # Counter of frames with no circle.  

    detector = createDetector()
    
    while True:
        # capture tool location in machine space before processing
        toolCoordinates = printer.getCoords()
        # capture first clean frame for display
        cleanFrame = get.frame
        # apply nozzle detection algorithm
        if not alternate:
            # Detection algorithm 1:
            #    gamma correction -> use Y channel from YUV -> GaussianBlur (7,7),6 -> adaptive threshold
            gammaInput = 1.2
            frame = adjust_gamma(cleanFrame, gammaInput)
            yuv = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV)
            yuvPlanes = cv2.split(yuv)
            yuvPlanes[0] = cv2.GaussianBlur(yuvPlanes[0],(7,7),6)
            yuvPlanes[0] = cv2.adaptiveThreshold(yuvPlanes[0],255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY,35,1)
            edgeDetectedFrame = cv2.cvtColor(yuvPlanes[0],cv2.COLOR_GRAY2BGR)
            frame = cv2.cvtColor(yuvPlanes[0],cv2.COLOR_GRAY2BGR)
            target = [int(np.around(frame.shape[1]/2)),int(np.around(frame.shape[0]/2))]
            # run nozzle detection for keypoints
            keypoints = detector.detect(frame)
        else:
            # Detection algorithm 2
            #    use B channel from BGR -> medianBlur (3) -> equalize histogram -> GaussianBlur (7,7),6
            edgeDetectedFrame = cv2.split(cleanFrame)[0]
            edgeDetectedFrame = cv2.medianBlur( edgeDetectedFrame, 3 )
            cv2.equalizeHist(edgeDetectedFrame, edgeDetectedFrame)
            edgeDetectedFrame = cv2.GaussianBlur( edgeDetectedFrame, (7,7), 6 )
            edgeDetectedFrame = cv2.cvtColor(edgeDetectedFrame,cv2.COLOR_GRAY2BGR)
            target = [int(np.around(edgeDetectedFrame.shape[1]/2)),int(np.around(edgeDetectedFrame.shape[0]/2))]
            # run nozzle detection for keypoints
            keypoints = detector.detect(edgeDetectedFrame)
        
        # draw the timestamp on the frame AFTER the circle detector! Otherwise it finds the circles in the numbers.
        # place the cleanFrame capture into display to avoid showing edge detection and other confusing images
        frame = putText(cleanFrame,'timestamp',offsety=99)
        frame = cv2.line(frame, (target[0],    target[1]-25), (target[0],    target[1]+25), (0, 255, 0), 1)
        frame = cv2.line(frame, (target[0]-25, target[1]   ), (target[0]+25, target[1]   ), (0, 255, 0), 1)
        
        if(nocircle> 25):
            print( 'Error in detecting nozzle. Please check if focus is clear and nozzle is clear of filament. TAMV will continue attempting to process alignment.')
            show.text = "Error in detecting nozzle."
            nocircle = 0
            continue

        lk=len(keypoints)
        if (lk == 0):
            if (25 < (int(round(time.time() * 1000)) - rd)):
                #print('No circles found')
                nocircle += 1
                frame = putText(frame,'No circles found',offsety=3)
                #show.text = "No circles found."
                if( xray ):
                    #xray mode enabled, stack output
                    xrayFrame = np.hstack((frame, edgeDetectedFrame))
                    show.frame = xrayFrame
                else :
                    show.frame = frame
            continue
        if (lk > 1):
            if (25 < (int(round(time.time() * 1000)) - rd)):
                print('Too many circles found')
                show.text = "Too many circles found. Please stop and clean the nozzle."
                #printKeypointXYR(keypoints)
                frame = putText(frame,'Too many circles found '+str(lk),offsety=3, color=(255,255,255))                
                frame = cv2.drawKeypoints(frame, keypoints, np.array([]), (255,255,255), cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS)
                if( xray ):
                    #xray mode enabled, stack output
                    xrayFrame = np.hstack((frame, edgeDetectedFrame))
                    show.frame = xrayFrame
                else :
                    show.frame = frame
            continue
        # Found one and only one circle.  Put it on the frame.
        nocircle = 0 
        xy = np.around(keypoints[0].pt)
        r = np.around(keypoints[0].size/2)
        # draw the blobs that look circular
        frame = cv2.drawKeypoints(frame, keypoints, np.array([]), (0,0,255), cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS)
        # Note its radius and position
        ts =  "U{0:3.0f} V{1:3.0f} R{2:2.0f}".format(xy[0],xy[1],r)
        xy = np.uint16(xy)
        frame = putText(frame, ts, offsety=2, color=(0, 255, 0), stroke=2)
        # show the frame
        if( xray ):
            #xray mode enabled, stack output
            xrayFrame = np.hstack((frame, edgeDetectedFrame))
            show.frame = xrayFrame
        else :
            show.frame = frame
        rd = int(round(time.time() * 1000))
        #end the loop
        break

    # and tell our parent.
    return (xy, target, rotationInput, toolCoordinates, r)

def putText(frame,text,color=(0, 0, 255),offsetx=0,offsety=0,stroke=1):  # Offsets are in character box size in pixels. 
    if (text == 'timestamp'): text = datetime.datetime.now().strftime("%m-%d-%Y %H:%M:%S")
    fontScale = 1
    if (frame.shape[1] > 640): fontScale = stroke = 2
    if (frame.shape[1] < 640):
        fontScale = 0.8
        stroke = 1
    offpix = cv2.getTextSize('A',   cv2.FONT_HERSHEY_SIMPLEX ,fontScale, stroke)
    textpix = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX ,fontScale, stroke)
    offsety=max(offsety, (-frame.shape[0]/2 + offpix[0][1])/offpix[0][1]) # Let offsety -99 be top row
    offsetx=max(offsetx, (-frame.shape[1]/2 + offpix[0][0])/offpix[0][0]) # Let offsetx -99 be left edge
    offsety=min(offsety,  (frame.shape[0]/2 - offpix[0][1])/offpix[0][1]) # Let offsety  99 be bottom row. 
    offsetx=min(offsetx,  (frame.shape[1]/2 - offpix[0][0])/offpix[0][0]) # Let offsetx  99 be right edge. 
    cv2.putText(frame, text, 
        (int(offsetx * offpix[0][0]) + int(frame.shape[1]/2) - int(textpix[0][0]/2)
        ,int(offsety * offpix[0][1]) + int(frame.shape[0]/2) + int(textpix[0][1]/2)),
        cv2.FONT_HERSHEY_SIMPLEX, fontScale, color, stroke)
    return(frame)



###################################################################################
# End of method definitions
# Start of Main Code
###################################################################################
def main(video_shower, video_getter, printer):
    try:
        if(vidonly):
            vidWindow(video_getter,video_shower)
            return(video_shower, video_getter)
        
        if ( cp[1] == -999 and cp[0] == -999 ):
            (video_getter, video_shower, CPCoords) = controlledPoint(video_getter, video_shower)                   # Command line -cp not supplied, find with help of user and camera. 
        else:
            CPCoords = {'X':cp[0], 'Y':cp[1]}   # Load -cp command line arg into dict like printerGetCoords
        
        # Make sure no tools are loaded to start
        print('')
        print( 'Unloading tools from machine carriage.')
        printer.gCode("T-1")
        if speedy:
            printer.gCode("G1 F13200")
            printer.gCode("M204 P2000 T2000")
            
        print('')
        
        # Now look at each tool and find alignment centers
        alignmentStartTime = time.time()
        toolCoords = []
        transformationMatrix = None
        mpp = 0
        video_shower.text = "Calibrating camera rotation..."
        # slow down Z jerk to improve repeatability
        # HBHBHB
        # printer.gCode("M566 Z10")
        # printer.gCode("M201 Z50")
        # printer.gCode("M203 Z120")
        # HBHBHB
        for r in range(0,repeat):
            toolCoords.append([])
            for t in range(printer.getNumTools()):
                connectionAlive = True
                try:
                    while connectionAlive:
                        printer.gCode("T-1 ")
                        toolStartTime = time.time()
                        _result, transformationMatrix,mpp = eachTool(t,r,video_getter,video_shower, CPCoords, transformationMatrix, mpp)
                        toolCoords[r].append(_result)
                        toolEndTime = time.time()
                        print( 'Tool ' + str(t) + ' ran in ' + str(int(toolEndTime-toolStartTime))+ ' seconds.')
                        toolOffsets = printer.getG10ToolOffset(t)
                        x = np.around((CPCoords['X'] + toolOffsets['X']) - toolCoords[r][t]['X'],3)
                        y = np.around((CPCoords['Y'] + toolOffsets['Y']) - toolCoords[r][t]['Y'],3)
                        printer.gCode("G10 P{0:d} X{1:1.3f} Y{2:1.3f} ".format(t,x,y))
                        video_shower.text = "Offset for T{0:d}: X{1:1.3f} Y{2:1.3f}".format(t,x,y)
                        # HBHBHB
                        #printer.gCode("M566 Z10")
                        #printer.gCode("M201 Z50")
                        #printer.gCode("M203 Z120")
                        # HBHBHB
                        connectionAlive = False
                except Exception as cr1:
                    # Duet disconnected, reconnect
                    #userInput = input('Connection dropped, retry?')
                    if True: #userInput in ['Y','y']:
                        print('Connection dropped. Retrying.')
                        printer = DWA.DuetWebAPI('http://'+duet)
                        connectionAlive = True
                        oolStartTime = time.time()
                        _result, transformationMatrix,mpp = eachTool(t,r,video_getter,video_shower, CPCoords, transformationMatrix, mpp)
                        toolCoords[r].append(_result)
                        toolEndTime = time.time()
                        print( 'Tool ' + str(t) + ' ran in ' + str(int(toolEndTime-toolStartTime))+ ' seconds.')
                        toolOffsets = printer.getG10ToolOffset(t)
                        x = np.around((CPCoords['X'] + toolOffsets['X']) - toolCoords[r][t]['X'],3)
                        y = np.around((CPCoords['Y'] + toolOffsets['Y']) - toolCoords[r][t]['Y'],3)
                        printer.gCode("G10 P{0:d} X{1:1.3f} Y{2:1.3f} ".format(t,x,y))
                        video_shower.text = "Offset for T{0:d}: X{1:1.3f} Y{2:1.3f}".format(t,x,y)
                        continue
                    else:
                        print( "Terminating TAMV run due to disconnection." )
                        return(video_shower, video_getter)
                        
                    
            alignmentEndTime = time.time()
            print('')
            print( 'Total calibration time so far: ' + str(int(alignmentEndTime - alignmentStartTime)) + ' seconds.' )
        print('')
        print("Unmounting last tool and resetting config file defaults..")
        printer.gCode("T-1 ")
        printer.resetAdvancedMovement()

        ###################################################################################
        # End of all vision, etc.  Now calculate and report.
        ###################################################################################
        print('')
        alignmentText = ''
        for t in range(0,len(toolCoords[0])):
            toolOffsets = printer.getG10ToolOffset(t)
            x = np.around((CPCoords['X'] + toolOffsets['X']) - toolCoords[0][t]['X'],3)
            y = np.around((CPCoords['Y'] + toolOffsets['Y']) - toolCoords[0][t]['Y'],3)
            mpp = str(toolCoords[0][t]['MPP'])
            alignmentText += "G10 P{0:d} X{1:1.3f} Y{2:1.3f} ".format(t,x,y) + '\n'
            print( 'Alignment for tool ' + str(t) + ' took ' + str(int(toolCoords[0][t]['time'])) + ' seconds. (MPP=' + mpp + ')' )
            #printer.gCode("G10 P{0:d} X{1:1.3f} Y{2:1.3f} ".format(t,x,y))
        # display G10 offset statements on terminal screen
        print('')
        print( 'Here are the G10 offset g-code commands to run for your printer to apply these offsets:')
        print( alignmentText )
        print('')

        if (repeat > 1): 
            print('Calibration control point at X{0:1.3f} Y{1:1.3f} '.format(CPCoords['X'],CPCoords['Y']))
            repeatReport(toolCoords, repeat)  

        print('')
        print("Tool offsets have been applied to the current printer.")
        print("Please modify your tool definitions in config.g to reflect these newly measured values for persistent storage.")
        print('')
        print('If your camera is in a consistent location, next time you run TAMV, you can optionally supply:' )
        print('-cp {0:1.3f} {1:1.3f} '.format(CPCoords['X'],CPCoords['Y']))
        print('Adding this will cause TAMV to skip all interaction, and attempt to align all tools on its own.')
        print('(This is the real absolute X & Y location of your camera on your machine.)')
        
        return(video_shower, video_getter)
    except Exception as e1:
        #video_shower.stop()
        #video_getter.stop()
        print("Uknown error in main function!")
        print(e1)
        import traceback
        exc_info = sys.exc_info()
        traceback.print_exception(*exc_info)
        return(video_shower, video_getter)

if __name__ == "__main__":
    #global video_shower, video_getter
    try:
        init()
        #cv2.namedWindow("Parameters",cv2.WINDOW_AUTOSIZE)
        #cv2.createTrackbar("area","Parameters",0,1,callbackButton)
        #cv2.createButton('test',callbackButton)
        #if xray: buttonXray = 1
        #else: buttonXray = 0
        #cv2.createButton("X-ray",callbackButton,cv2.QT_CHECKBOX, buttonXray)
        # set up video capture thread
        video_getter = VideoGet(camera)
        video_getter_thread = threading.Thread(target=video_getter.get)
        video_getter_thread.daemon = True
        video_getter_thread.start()

        tempFrame = video_getter.frame
        video_shower = VideoShow(tempFrame)
        video_shower_thread = threading.Thread(target=video_shower.show)
        video_shower_thread.daemon = True
        video_shower_thread.start()
        #cv2.namedWindow("TAMV",cv2.WINDOW_AUTOSIZE)
        #cv2.imshow("TAMV",video_shower.frame)
        #cv2.displayOverlay("TAMV",video_shower.text )
        (video_shower, video_getter) = main(video_shower, video_getter, printer)
    except Exception as v1:
        print( 'ERROR: Video capture failed' )
        print( v1 )
        video_getter.stop()
        video_shower.stop()
        cv2.destroyAllWindows()
        sys.exit(1)
    video_shower.stop()
    video_getter.stop()
    cv2.destroyAllWindows()
    sys.exit(0)

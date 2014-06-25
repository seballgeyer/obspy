from math import pi
from taupy.VelocityLayer import VelocityLayer
from taupy.SlownessLayer import SlownessLayer

class SlownessModelError(Exception):
    pass
class CriticalDepth:
    def __init__(self, depth, velLayerNum, pLayerNum, sLayerNum):
        self.depth = depth
        self.velLayerNum = velLayerNum;
        self.sLayerNum = pLayerNum;
        self.sLayerNum = pLayerNum;
class DepthRange:
    def __init__(self, topDepth = None, botDepth = None, rayParam = -1):
        self.topDepth = topDepth;
        self.botDepth = botDepth;
        self.rayParam = rayParam

class SlownessModel(object):
    """This class provides storage and methods for generating slowness-depth pairs."""
    DEBUG = False
    DEFAULT_SLOWNESS_TOLERANCE = 500
    
    # NB if the following are actually cleared (lists are mutable) every
    # time createSample is called, maybe it would be better to just put these
    # initialisations into the relevant methods? They do have to be persistent across
    # method calls in createSample though (maybe??).

    #  Stores the layer number for layers in the velocity model with a critical
    # point at their top. These form the "branches" of slowness sampling.
    criticalDepths = [] # will be list of CriticalDepth objects
    # Store depth ranges that contains a high slowness zone for P/S. Stored as
    # DepthRange objects, containing the top depth and bottom depth.
    highSlownessLayerDepthsP = [] # will be list of DepthRanges
    highSlownessLayerDepthsS = []
    # Stores depth ranges that are fluid, ie S velocity is zero. Stored as
    # DepthRange objects, containing the top depth and bottom depth.
    fluidLayerDepths = []

    # For methods that have an isPWave parameter
    SWAVE = False
    PWAVE = True
    
    def __init__(self, vMod, minDeltaP=0.1, maxDeltaP=11, maxDepthInterval=115, maxRangeInterval=2.5*pi/180, maxInterpError=0.05, allowInnerCoreS=True, slowness_tolerance=500):
        
        self.vMod = vMod
        self.minDeltaP = minDeltaP
        self.maxDeltaP = maxDeltaP
        self.maxDepthInterval = maxDepthInterval
        self.maxRangeInterval = maxRangeInterval
        self.maxInterpError = maxInterpError
        self.allowInnerCoreS = allowInnerCoreS
        self.slowness_tolerance = slowness_tolerance
        self.createSample()

    def createSample(self):
        ''' This method takes a velocity model and creates a vector containing
        slowness-depth layers that, hopefully, adequately sample both slowness
        and depth so that the travel time as a function of distance can be
        reconstructed from the theta function.'''
        # Some checks on the velocity model
        if self.vMod.validate() == False:
            raise SlownessModelError("Error in velocity model (vMod.validate failed)!")
        if self.vMod.getNumLayers() == 0:
            raise SlownessModelError("velModel.getNumLayers()==0")
        if self.vMod.layers[0].topSVelocity == 0:
            raise SlownessModelError("Unable to handle zero S velocity layers at surface. This should be fixed at some point, but is a limitation of TauP at this point.")
        if self.DEBUG:
            print("start createSample")

        self.radiusOfEarth = self.vMod.radiusOfEarth

        if self.DEBUG: print("findCriticalPoints")
        self.findCriticalPoints()
        if self.DEBUG: print("coarseSample")
        self.coarseSample()
        if self.DEBUG and self.validate() != True: 
            raise(SlownessModelError('validate failed after coarseSample'))
        if self.DEBUG: print("rayParamCheck")
        self.rayParamIncCheck()
        if self.DEBUG: print("depthIncCheck")
        self.depthIncCheck()
        if self.DEBUG: print("distanceCheck")
        self.distanceCheck()
        if self.DEBUG: print("fixCriticalPoints")
        self.fixCriticalPoints()
        
        if self.validate() == True: 
            print("createSample seems to be done successfully.")
        else:
            raise SlownessModelError('SlownessModel.validate failed!')

    def findCriticalPoints(self):
        ''' Finds all critical points within a velocity model.

         Critical points are first order discontinuities in
        velocity/slowness, local extrema in slowness. A high slowness
        zone is a low velocity zone, but it is possible to have a
        slight low velocity zone within a spherical earth that is not
        a high slowness zone and thus does not exhibit any of the
        pathological behavior of a low velocity zone.  '''
        inFluidZone = False
        belowOuterCore = False
        inHighSlownessZoneP = False
        inHighSlownessZoneS = False
        # just some very big values (java had max possible of type, but these should do)
        minPSoFar = 1.1e300
        minSSoFar = 1.1e300
        # First remove any critical points previously stored
        # so these are effectively re-initialised... it's probaby silly
        self.criticalDepths = [];           # list of CriticalDepth
        self.highSlownessLayerDepthsP = []; # lists of DepthRange
        self.highSlownessLayerDepthsS = [];
        self.fluidLayerDepths = [];
        # Initialize the current velocity layer
        # to be zero thickness layer with values at the surface
        currVLayer = self.vMod.layers[0]
        currVLayer = VelocityLayer(0, currVLayer.topDepth, currVLayer.topDepth,
                                   currVLayer.topPVelocity, currVLayer.topPVelocity,
                                   currVLayer.topSVelocity, currVLayer.topSVelocity,
                                   currVLayer.topDensity, currVLayer.topDensity,
                                   currVLayer.topQp, currVLayer.topQp,
                                   currVLayer.topQs, currVLayer.topQs)
        currSLayer = SlownessLayer.create_from_vlayer(currVLayer, self.SWAVE)
        currPLayer = SlownessLayer.create_from_vlayer(currVLayer, self.PWAVE)
        # We know that the top is always a critical slowness so add 0
        self.criticalDepths.append(CriticalDepth(0,0,0,0))
        # Check to see if starting in fluid zone.
        if inFluidZone != True and currVLayer.topSVelocity == 0:
            inFluidZone = True
            fluidZone = DepthRange(topDepth = currVLayer.topDepth)
            currSLayer = currPLayer
        if minSSoFar > currSLayer.topP:
            minSSoFar = currSLayer.topP
        # P is not a typo, it represents slowness, not P-wave speed.
        if minPSoFar > currPLayer.topP:
            minPSoFar = currPLayer.topP

        for layerNum, layer in enumerate(self.vMod.layers):
            prevVLayer = currVLayer
            prevSLayer = currSLayer
            prevPLayer = currPLayer
            # Could make this a deep copy, but not necessary (yet?)
            currVLayer = layer
            # Check again if in fluid zone
            if inFluidZone != True and currVLayer.topSVelocity == 0:
                inFluidZone = True
                fluidZone = DepthRange(topDepth = currVLayer.topDepth)
            # If already in fluid zone, check if exited
            if inFluidZone == True and currVLayer.topSVelocity != 0:
                if prevVLayer.botDepth > self.vMod.iocbDepth:
                    belowOuterCore = True
                inFluidZone = False
                fluidZone.botDepth = prevVLayer.botDepth
                self.fluidLayerDepths.append(fluidZone)
            
            currPLayer = SlownessLayer.create_from_vlayer(currVLayer, self.PWAVE)
            # If we are in a fluid zone ( S velocity = 0.0 ) or if we are below
            # the outer core and allowInnerCoreS=false then use the P velocity
            # structure to look for critical points.
            if inFluidZone or (belowOuterCore and self.allowInnerCoreS != True):
                currSLayer = currPLayer
            else:
                currSLayer = SlownessLayer.create_from_vlayer(currVLayer, self.SWAVE)

            if prevSLayer.botP != currSLayer.topP or prevPLayer.botP != currPLayer.topP:
                # a first order discontinuity
                self.criticalDepths.append(CriticalDepth(currSLayer.topDepth,
                                                         layerNum, -1, -1))
                if self.DEBUG:
                    print('First order discontinuity, depth =' + str(currSLayer.topDepth))
                    print('between' + str(prevPLayer), currPLayer)
                if inHighSlownessZoneS and currSLayer.topP < minSSoFar:
                    if self.DEBUG:
                        print("Top of current layer is the bottom"
                                + " of a high slowness zone.")
                    highSlownessZoneS = DepthRange(botDepth = currSLayer.topDepth)
                    self.highSlownessLayerDepthsS.append(highSlownessZoneS)
                    inHighSlownessZoneS = False;
                if inHighSlownessZoneP and currPLayer.topP < minPSoFar:
                    if self.DEBUG:
                        print("Top of current layer is the bottom"
                                + " of a high slowness zone.")
                    highSlownessZoneP = DepthRange(botDepth = currSLayer.topDepth)
                    self.highSlownessLayerDepthsP.append(highSlownessZoneP)
                    inHighSlownessZoneP = False;
                # Update minPSoFar and minSSoFar as all total reflections off
                # of the top of the discontinuity are ok even though below the
                # discontinuity could be the start of a high slowness zone.
                if minPSoFar > currPLayer.topP:
                    minPSoFar = currPLayer.topP
                if minSSoFar > currSLayer.topP:
                    minSSoFar = currSLayer.topP
                    
                if inHighSlownessZoneS != True and (prevSLayer.botP < currSLayer.topP or
                                                    currSLayer.topP < currSLayer.botP):
                    # start of a high slowness zone
                    if self.DEBUG:
                        print("Found S high slowness at first order "
                              + "discontinuity, layer = " + str(layerNum))
                    inHighSlownessZoneP = True
                    highSlownessZoneP = DepthRange(topDepth = currPLayer.topDepth)
                    highSlownessZoneP.rayParam = minPSoFar
            else:
                if ((prevSLayer.topP - prevSLayer.botP) *
                    (prevSLayer.botP - currSLayer.botP) < 0 ) or (
                    (prevPLayer.topP - prevPLayer.botP) *
                    (prevPLayer.botP - currPLayer.botP)) < 0:
                    # local slowness extrema
                    self.criticalDepths.append(CriticalDepth(currSLayer.topDepth, layerNum,
                                                             -1, -1))
                    if self.DEBUG:
                        print("local slowness extrema, depth=" + str(currSLayer.topDepth))
                    
             # here is line 1014 of the java src!

    



    def coarseSample(self):
        pass
    def rayParamIncCheck(self):
        pass
    def depthIncCheck(self):
        pass
    def distanceCheck(self):
        pass
    def fixCriticalPoints(self):
        pass
    def validate(self):
        return True
    def getNumLayers(self, isPWave):
        '''This is meant to return the number of pLayers and sLayers.
        I have not yet been able to find out how these are known in 
        the java code.'''
        # translated Java code:
        # def getNumLayers(self, isPWave):
        # """ generated source for method getNumLayers """
        # if isPWave:
        #     return len(self.PLayers)
        # else:
        #     return len(self.SLayers)

        # Where
        # self.PLayers = pLayers
        # and the pLayers have been provided in the constructor, but I
        # don't understand from where!

        # dummy code so TauP_Create won't fail:
        if isPWave == True:
            return 'some really dummy number'
        if isPWave == False:
            return 'some other number'

            
    def __str__(self):
        desc = "This is a dummy SlownessModel so there's nothing here really. Nothing to see. Move on."
        desc += "This might be interesting: slowness_tolerance ought to be 500. It is:" + str(self.slowness_tolerance)
        return desc

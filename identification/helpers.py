from __future__ import division
from __future__ import print_function
from builtins import str
from builtins import range
from builtins import object
import time
import iDynTree
import numpy as np

import colorama
from colorama import Fore, Back, Style

import sys
if (sys.version_info < (3, 0)):
    class FileNotFoundError(OSError):
        pass

from tqdm import tqdm

class Progress(object):
    def __init__(self, config):
        self.config = config

    def progress(self, iter):
        if self.config['verbose']:
            return tqdm(iter)
        else:
            return iter

class Timer(object):
    def __enter__(self):
        self.start = time.clock()
        return self

    def __exit__(self, *args):
        self.end = time.clock()
        self.interval = self.end - self.start

class ParamHelpers(object):
    def __init__(self, model, opt):
        self.model = model
        self.opt = opt

    def checkPhysicalConsistency(self, params, full=False):
        """
        check params for physical consistency
        (mass positive, inertia tensor positive definite, triangle inequaltiy for eigenvalues of inertia tensor expressed at COM)

        expect params relative to link frame
        returns dictionary of link ids and boolean consistency for each link

        when full is True, a 10 parameter per link vector is expected, regardless of global options
        """
        cons = {}
        if self.opt['identifyGravityParamsOnly'] and not full:
            for i in range(0, self.model.num_links):
                #masses need to be positive
                cons[i] = params[i*4] > 0
        else:
            for i in range(0, len(params)):
                if (i % 10 == 0) and i < self.model.num_model_params:   #for each link (and not friction)
                    p_vec = iDynTree.Vector10()
                    for j in range(0, 10):
                        p_vec.setVal(j, params[i+j])
                    si = iDynTree.SpatialInertia()
                    si.fromVector(p_vec)
                    cons[i // 10] = si.isPhysicallyConsistent()
        return cons

    def checkPhysicalConsistencyNoTriangle(self, params, full=False):
        """
        check params for physical consistency
        (mass positive, inertia tensor positive definite)

        expect params relative to link frame
        returns dictionary of link ids and boolean consistency for each link

        when full is True, a 10 parameter per link vector is expected, regardless of global options
        """
        cons = {}
        if self.opt['identifyGravityParamsOnly'] and not full:
            for i in range(0, self.model.num_links):
                #masses need to be positive
                cons[i] = params[i*4] > 0
        else:
            tensors = self.inertiaTensorFromParams(params)
            for i in range(0, len(params)):
                if (i % 10 == 0) and i < self.model.num_model_params:
                    if params[i] <= 0:  #masses need to be positive
                        cons[i // 10] = False
                        continue
                    #check if inertia tensor is positive definite (only then cholesky decomp exists)
                    try:
                        np.linalg.cholesky(tensors[i // 10])
                        cons[i // 10] = True
                    except np.linalg.linalg.LinAlgError:
                        cons[i // 10] = False
                else:
                    #TODO: check friction params >0
                    pass

        '''
        if False in cons.values():
            print(Fore.RED + "Params are not consistent but ATM ignored" + Fore.RESET)
            print(cons)
        for k in cons:
            cons[k] = True
        '''
        return cons

    def isPhysicalConsistent(self, params):
        """give boolean consistency statement for a set of parameters"""
        return not (False in self.checkPhysicalConsistencyNoTriangle(params).values())

    def invvech(self, params):
        """give full inertia tensor from vectorized form
           expect vector of 6 values (xx, xy, xz, yy, yz, zz).T"""
        tensor = np.zeros((3,3))
        #xx of tensor matrix
        value = params[0]
        tensor[0, 0] = value
        #xy
        value = params[1]
        tensor[0, 1] = value
        tensor[1, 0] = value
        #xz
        value = params[2]
        tensor[0, 2] = value
        tensor[2, 0] = value
        #yy
        value = params[3]
        tensor[1, 1] = value
        #yz
        value = params[4]
        tensor[1, 2] = value
        tensor[2, 1] = value
        #zz
        value = params[5]
        tensor[2, 2] = value
        return tensor

    def vech(self, params):
        #return vectorization of symmetric 3x3 matrix (only up to diagonal)
        vec = np.zeros(6)
        vec[0] = params[0,0]
        vec[1] = params[0,1]
        vec[2] = params[0,2]
        vec[3] = params[1,1]
        vec[4] = params[1,2]
        vec[5] = params[2,2]
        return vec

    def inertiaTensorFromParams(self, params):
        """take a parameter vector and return list of full inertia tensors (one for each link)"""
        tensors = list()
        for i in range(len(params)):
            if (i % 10 == 0) and i < self.model.num_model_params:
                tensor = self.invvech(params[i+4:i+10])
                tensors.append(tensor)
        return tensors

    def inertiaParams2RotationalInertiaRaw(self, params):
        #take values from inertia parameter vector and create iDynTree RotationalInertiaRaw matrix
        #expects six parameter vector

        inertia = iDynTree.RotationalInertiaRaw()
        #xx of inertia matrix w.r.t. link origin
        value = params[0]
        inertia.setVal(0, 0, value)
        #xy
        value = params[1]
        inertia.setVal(0, 1, value)
        inertia.setVal(1, 0, value)
        #xz
        value = params[2]
        inertia.setVal(0, 2, value)
        inertia.setVal(2, 0, value)
        #yy
        value = params[3]
        inertia.setVal(1, 1, value)
        #yz
        value = params[4]
        inertia.setVal(1, 2, value)
        inertia.setVal(2, 1, value)
        #zz
        value = params[5]
        inertia.setVal(2, 2, value)
        return inertia

    def paramsLink2Bary(self, params):
        ## convert params from iDynTree values (relative to link frame) to barycentric parameters (usable in URDF)
        ## (changed in place)

        #mass stays the same
        #linear com is first moment of mass, so com * mass. URDF uses com
        #linear inertia is expressed w.r.t. frame origin (-m*S(c).T*S(c)). URDF uses w.r.t com
        params = params.copy()
        for i in range(0, len(params)):
            if (i % 10 == 0) and i < self.model.num_model_params:   #for each link
                link_mass = params[i]
                #com
                com_x = params[i+1]
                com_y = params[i+2]
                com_z = params[i+3]
                if link_mass != 0:
                    params[i+1] = com_x / link_mass  #x of first moment -> x of com
                    params[i+2] = com_y / link_mass  #y of first moment -> y of com
                    params[i+3] = com_z / link_mass  #z of first moment -> z of com
                else:
                    params[i+1] = params[i+2] = params[i+3] = 0
                p_com = iDynTree.PositionRaw(params[i+1], params[i+2], params[i+3])

                #inertias
                rot_inertia_origin = self.inertiaParams2RotationalInertiaRaw(params[i+4:i+10])
                s_inertia = iDynTree.SpatialInertia(link_mass, p_com, rot_inertia_origin)
                rot_inertia_com = s_inertia.getRotationalInertiaWrtCenterOfMass()
                params[i+4] = rot_inertia_com.getVal(0, 0)    #xx w.r.t. com
                params[i+5] = rot_inertia_com.getVal(0, 1)    #xy w.r.t. com
                params[i+6] = rot_inertia_com.getVal(0, 2)    #xz w.r.t. com
                params[i+7] = rot_inertia_com.getVal(1, 1)    #yy w.r.t. com
                params[i+8] = rot_inertia_com.getVal(1, 2)    #yz w.r.t. com
                params[i+9] = rot_inertia_com.getVal(2, 2)    #zz w.r.t. com
        return params

    def paramsBary2Link(self, params):
        params = params.copy()
        for i in range(0, len(params)):
            if (i % 10 == 0) and i < self.model.num_model_params:   #for each link
                link_mass = params[i]
                #com
                com_x = params[i+1]
                com_y = params[i+2]
                com_z = params[i+3]
                params[i+1] = com_x * link_mass  #x of first moment of mass
                params[i+2] = com_y * link_mass  #y of first moment of mass
                params[i+3] = com_z * link_mass  #z of first moment of mass
                p_com = iDynTree.PositionRaw(params[i+1], params[i+2], params[i+3])

                #inertias
                rot_inertia_com = self.inertiaParams2RotationalInertiaRaw(params[i+4:i+10])
                s_inertia = iDynTree.SpatialInertia(link_mass, p_com, rot_inertia_com)
                s_inertia.fromRotationalInertiaWrtCenterOfMass(link_mass, p_com, rot_inertia_com)
                rot_inertia = s_inertia.getRotationalInertiaWrtFrameOrigin()
                params[i+4] = rot_inertia.getVal(0, 0)    #xx w.r.t. com
                params[i+5] = rot_inertia.getVal(0, 1)    #xy w.r.t. com
                params[i+6] = rot_inertia.getVal(0, 2)    #xz w.r.t. com
                params[i+7] = rot_inertia.getVal(1, 1)    #yy w.r.t. com
                params[i+8] = rot_inertia.getVal(1, 2)    #yz w.r.t. com
                params[i+9] = rot_inertia.getVal(2, 2)    #zz w.r.t. com

        return params

    @staticmethod
    def addFrictionFromURDF(model, urdf_file, params):
        ''' get friction vals from urdf (joint friction = fc, damping= fv) and set in params vector'''

        friction = URDFHelpers.getJointFriction(urdf_file)
        nd = model.num_dofs
        start = model.num_model_params
        end = start + nd
        params[start:end] = np.array([friction[f]['f_constant'] for f in sorted(friction.keys())])
        if not model.opt['identifyGravityParamsOnly']:
            start = model.num_model_params+nd
            end = start + nd
            params[start:end] = np.array([friction[f]['f_velocity'] for f in sorted(friction.keys())])
            if not model.opt['identifySymmetricVelFriction']:
                params[start+nd:end+nd] = \
                    np.array([friction[f]['f_velocity'] for f in sorted(friction.keys())])

class URDFHelpers(object):
    def __init__(self, paramHelpers, model, opt):
        self.paramHelpers = paramHelpers
        self.model = model
        self.opt = opt

    def replaceParamsInURDF(self, input_urdf, output_urdf, new_params):
        """ set new inertia parameters from params and urdf_file, write to new temp file """

        if self.opt['identifyGravityParamsOnly']:
            per_link = 4
            xStdBary = new_params.copy()
            for i in range(len(new_params)):
                if i % per_link == 0:
                    xStdBary[i+1:i+3+1] /= xStdBary[i]
        else:
            per_link = 10
            xStdBary = self.paramHelpers.paramsLink2Bary(new_params)

        import xml.etree.ElementTree as ET
        tree = ET.parse(input_urdf)
        for l in tree.findall('link'):
            if l.attrib['name'] in self.model.linkNames:
                link_id = self.model.linkNames.index(l.attrib['name'])
                l.find('inertial/mass').attrib['value'] = '{}'.format(xStdBary[link_id*per_link])
                l.find('inertial/origin').attrib['xyz'] = '{} {} {}'.format(xStdBary[link_id*per_link+1],
                                                                            xStdBary[link_id*per_link+2],
                                                                            xStdBary[link_id*per_link+3])
                if not self.opt['identifyGravityParamsOnly']:
                    inert = l.find('inertial/inertia')
                    inert.attrib['ixx'] = '{}'.format(xStdBary[link_id*10+4])
                    inert.attrib['ixy'] = '{}'.format(xStdBary[link_id*10+5])
                    inert.attrib['ixz'] = '{}'.format(xStdBary[link_id*10+6])
                    inert.attrib['iyy'] = '{}'.format(xStdBary[link_id*10+7])
                    inert.attrib['iyz'] = '{}'.format(xStdBary[link_id*10+8])
                    inert.attrib['izz'] = '{}'.format(xStdBary[link_id*10+9])


        # write friction of joints
        for l in tree.findall('joint'):
            if l.attrib['name'] in self.model.jointNames:
                joint_id = self.model.jointNames.index(l.attrib['name'])
                if self.opt['identifyFriction']:
                    f_c = xStdBary[self.model.num_links*per_link + joint_id]
                    if self.opt['identifyGravityParamsOnly']:
                        f_v = 0.0
                    else:
                        if self.opt['identifySymmetricVelFriction']:
                            f_v = xStdBary[self.model.num_model_params + self.model.num_dofs + joint_id]
                        else:
                            print(Fore.RED + "Can't write velocity dependent friction to URDF as identified values are asymmetric. URDF only supports symmetric values.")
                            sys.exit(1)
                else:
                    # parameters were identified assuming there was no friction
                    f_c = f_v = 0.0
                l.find('dynamics').attrib['friction'] = '{}'.format(f_c)
                l.find('dynamics').attrib['damping'] = '{}'.format(f_v)

        tree.write(output_urdf, xml_declaration=True)

    def getMeshPath(self, input_urdf, link_name):
        import xml.etree.ElementTree as ET
        tree = ET.parse(input_urdf)

        link_found = False
        filepath = None
        for l in tree.findall('link'):
            if l.attrib['name'] == link_name:
                link_found = True
                m = l.find('visual/geometry/mesh')
                if m != None:
                    filepath = m.attrib['filename']
                    try:
                        self.mesh_scaling = m.attrib['scale']
                    except KeyError:
                        self.mesh_scaling = '1 1 1'

        if not link_found or m is None:
            #print(Fore.RED + "No mesh information specified for link '{}' in URDF! Using a very large box.".format(link_name) + Fore.RESET)
            filepath = None
        else:
            if not filepath.lower().endswith('stl'):
                raise ValueError("Can't open other than STL files.")
                # TODO: could use pycollada for *.dae

        #if path is ros package path, get absolute system path
        if filepath and (filepath.startswith('package') or filepath.startswith('model')):
            try:
                import resource_retriever    #ros package
                r = resource_retriever.get(filepath)
                filepath = r.url.replace('file://', '')
                #r.read() #get file into memory
            except ImportError:
                #if no ros installed, try to get stl files from 'meshes' dir relative to urdf files
                filename = filepath.split('/')
                try:
                    filename = filename[filename.index(self.opt['meshBaseDir']):]
                    filepath = '/'.join(input_urdf.split('/')[:-1] + filename)
                except ValueError:
                    filepath = None

        return filepath

    def getBoundingBox(self, input_urdf, old_com, link_nr):
        ''' Return bounding box for one link derived from mesh file if possible.
            If no mesh file is found, a cube around the old COM is returned.
            Expects old_com in barycentric form! '''

        from stl import mesh   #using numpy-stl
        link_name = self.model.linkNames[link_nr]
        #TODO: don't parse xml file each time (not a big amount of time though)
        filename = self.getMeshPath(input_urdf, link_name)

        # box around current COM in case no mesh is availabe
        length = self.opt['cubeSize']
        cube = [(-0.5*length+old_com[0], 0.5*length+old_com[0]), (-0.5*length+old_com[1], 0.5*length+old_com[1]),
                (-0.5*length+old_com[2], 0.5*length+old_com[2])]
        #TODO: if <visual><box> is specified, use the size from there (also ellipsoid etc. could be done)

        if filename:
            try:
                stl_mesh = mesh.Mesh.from_file(filename)
                scale = self.opt['hullScaling']

                #gazebo and urdf use 1m for 1 stl unit
                scale_x = float(self.mesh_scaling.split()[0])
                scale_y = float(self.mesh_scaling.split()[1])
                scale_z = float(self.mesh_scaling.split()[2])

                bounding_box = [[stl_mesh.x.min()*scale_x*scale, stl_mesh.x.max()*scale_x*scale],
                                [stl_mesh.y.min()*scale_y*scale, stl_mesh.y.max()*scale_y*scale],
                                [stl_mesh.z.min()*scale_z*scale, stl_mesh.z.max()*scale_z*scale]]
                # switch order of min/max if scaling is negative
                for s in range(0,3):
                    if [scale_x, scale_y, scale_z][s] < 0:
                        bounding_box[s][0], bounding_box[s][1] = bounding_box[s][1], bounding_box[s][0]

                return bounding_box
            except FileNotFoundError:
                print(Fore.YELLOW + "Mesh file {} not found for link '{}'! Using a {}m cube around a priori COM.".format(filename, link_name, length) + Fore.RESET)
                return cube
        else:
            #in case there is no stl file in urdf
            print(Fore.YELLOW + "No mesh file given/found for link '{}'! Using a {}m cube around a priori COM.".format(link_name, length) + Fore.RESET)
            return cube

    #TODO: replace with new idyntree method
    @staticmethod
    def getJointLimits(input_urdf, use_deg=True):
        import xml.etree.ElementTree as ET
        tree = ET.parse(input_urdf)
        limits = {}
        for j in tree.findall('joint'):
            name = j.attrib['name']
            torque = 0
            lower = 0
            upper = 0
            velocity = 0
            if j.attrib['type'] == 'revolute':
                l = j.find('limit')
                if l != None:
                    torque = l.attrib['effort']   #this is not really the physical limit but controller limit, but well
                    lower = l.attrib['lower']
                    upper = l.attrib['upper']
                    velocity = l.attrib['velocity']

                    limits[name] = {}
                    limits[name]['torque'] = float(torque)
                    if use_deg:
                        limits[name]['lower'] = np.rad2deg(float(lower))
                        limits[name]['upper'] = np.rad2deg(float(upper))
                        limits[name]['velocity'] = np.rad2deg(float(velocity))
                    else:
                        limits[name]['lower'] = float(lower)
                        limits[name]['upper'] = float(upper)
                        limits[name]['velocity'] = float(velocity)
        return limits

    @staticmethod
    def getJointFriction(input_urdf):
        ''' return friction values for each revolute joint from a urdf'''

        import xml.etree.ElementTree as ET
        tree = ET.parse(input_urdf)
        friction = {}
        for j in tree.findall('joint'):
            name = j.attrib['name']
            constant = 0
            vel_dependent = 0
            if j.attrib['type'] == 'revolute':
                l = j.find('dynamics')
                if l != None:
                    try:
                        constant = l.attrib['friction']
                    except KeyError:
                        constant = 0

                    try:
                        vel_dependent = l.attrib['damping']
                    except KeyError:
                        vel_dependent = 0

                    friction[name] = {}
                    friction[name]['f_constant'] = float(constant)
                    friction[name]['f_velocity'] = float(vel_dependent)
        return friction

# Original repsositry by haddock labs,
# licensed under the Apache License, Version 2.0.

# Modified by Luc Elliott, 24/04/2023, with the following modifications: 
#   Updated the code to be compatible with Python 3.7.
#   Updated the code to be compatible with the latest version of the TEMPy library.
#   Updated the code to be compatible with the latest version of the gemmi library.
#   

# For more information about the original code, please see https://github.com/haddocking/powerfit. 

# Your modified code follows...

from __future__ import absolute_import
from collections import defaultdict, OrderedDict
from string import capwords

import numpy as np

from .elements import ELEMENTS
import six
from six.moves import range
from six.moves import zip
import io
from pathlib import Path

# TEMPy Parsers
from TEMPy.protein.structure_parser import PDBParser, mmCIFParser, gemmi_helper_fns
# Cragnolini T, Sahota H, Joseph AP, Sweeney A, Malhotra S, Vasishtan D, Topf M (2021a) TEMPy2: A Python library with improved 3D electron microscopy density-fitting and validation workflows. Acta Crystallogr Sect D Struct Biol 77:41–47. doi:10.1107/S2059798320014928

from copy import copy
import gemmi


# records
MODEL = 'MODEL '
ATOM = 'ATOM  '
HETATM = 'HETATM'
TER = 'TER   '

MODEL_LINE = 'MODEL ' + ' ' * 4 + '{:>4d}\n'
ENDMDL_LINE = 'ENDMDL\n'
TER_LINE = 'TER   ' + '{:>5d}' + ' ' * 6 + '{:3s}' + ' ' + '{:1s}' + \
        '{:>4d}' + '{:1s}' + ' ' * 53 + '\n'
ATOM_LINE = '{:6s}' + '{:>5d}' + ' ' + '{:4s}' + '{:1s}' + '{:3s}' + ' ' + \
        '{:1s}' + '{:>4d}' + '{:1s}' + ' ' * 3 + '{:8.3f}' * 3 + '{:6.2f}' * 2 + \
        ' ' * 10 + '{:<2s}' + '{:2s}\n'
END_LINE = 'END   \n'

ATOM_DATA = ('record id name alt resn chain resi i x y z q b ' \
        'e charge').split()
TER_DATA = 'id resn chain resi i'.split()


def parse_pdb(infile):

    if isinstance(infile, io.TextIOBase):
        f = infile
    elif isinstance(infile, str):
        f = open(infile)
    else:
        raise TypeError('Input should be either a file or string.')

    pdb = defaultdict(list)
    model_number = 1
    for line in f:
        record = line[:6]
        if record in (ATOM, HETATM):
            pdb['model'].append(model_number)
            pdb['record'].append(record)
            pdb['id'].append(int(line[6:11]))
            name = line[12:16].strip()
            pdb['name'].append(name)
            pdb['alt'].append(line[16])
            pdb['resn'].append(line[17:20].strip())
            pdb['chain'].append(line[21])
            pdb['resi'].append(int(line[22:26]))
            pdb['i'].append(line[26])
            pdb['x'].append(float(line[30:38]))
            pdb['y'].append(float(line[38:46]))
            pdb['z'].append(float(line[46:54]))
            pdb['q'].append(float(line[54:60]))
            pdb['b'].append(float(line[60:66]))
            # Be forgiving when determining the element
            e = line[76:78].strip()
            if not e:
                # If element is not given, take the first non-numeric letter of
                # the name as element.
                for e in name:
                    if e.isalpha():
                        break
            pdb['e'].append(e)
            pdb['charge'].append(line[78: 80].strip())
        elif record == MODEL:
            model_number = int(line[10: 14])
    f.close()
    return pdb


def tofile(pdb, out):

    f = open(out, 'w')

    nmodels = len(set(pdb['model']))
    natoms = len(pdb['id'])
    natoms_per_model = int(natoms / nmodels)

    for nmodel in range(nmodels):
        offset = int(nmodel * natoms_per_model)
        
        # write MODEL record
        if nmodels > 1:
            f.write(MODEL_LINE.format(nmodel + 1))
        prev_chain = pdb['chain'][offset]
        for natom in range(natoms_per_model):
            index = offset + natom

            # write TER record
            current_chain = pdb['chain'][index]
            if prev_chain != current_chain:
                prev_record = pdb['record'][index - 1]
                if prev_record == ATOM:
                    line_data = [pdb[data][index - 1] for data in TER_DATA]
                    line_data[0] += 1
                    f.write(TER_LINE.format(*line_data))
                prev_chain = current_chain

            # write ATOM/HETATM record
            line_data = [pdb[data][index] for data in ATOM_DATA]
            # take care of the rules for atom name position
            e = pdb['e'][index]
            name = pdb['name'][index]
            if len(e) == 1 and len(name) != 4:
                line_data[2] = ' ' + name
            f.write(ATOM_LINE.format(*line_data))

        # write ENDMDL record
        if nmodels > 1:
            f.write(ENDMDL_LINE)

    f.write(END_LINE)
    f.close()


def pdb_dict_to_array(pdb):
    dtype = [('record', np.str_, 6), ('id', np.int32),
             ('name', np.str_, 4), ('alt', np.str_, 1),
             ('resn', np.str_, 4), ('chain', np.str_, 2),
             ('resi', np.int32), ('i', np.str_, 1), ('x', np.float64),
             ('y', np.float64), ('z', np.float64),
             ('q', np.float64), ('b', np.float64),
             ('e', np.str_, 2), ('charge', np.str_, 2),
             ('model', np.int32)]

    natoms = len(pdb['id'])
    pdb_array = np.empty(natoms, dtype=dtype)
    for data in ATOM_DATA:
        pdb_array[data] = pdb[data]
    pdb_array['model'] = pdb['model']
    return pdb_array


def pdb_array_to_dict(pdb_array):
    pdb = defaultdict(list)
    for data in ATOM_DATA:
        pdb[data] = pdb_array[data].tolist()
    pdb['model'] = pdb_array['model'].tolist()
    return pdb


class Structure(object):

    @classmethod
    def fromfile(cls, fid):
        
        """Initialize Structure from PDB-file"""
        
        try:
            fname = fid.name
        except AttributeError:
            fname = fid

        if fname[-3:] in ('pdb', 'ent'):
            prot = PDBParser.read_PDB_file(
                fid,
                fid,
                hetatm=False,
                water=False)
        elif fname[-3:] == 'cif':
            prot = mmCIFParser.read_mmCIF_file(
                fid,
                hetatm=True,
                water=False)
        else:
            raise IOError('Filetype not recognized.')
        
        return cls(prot)

    @classmethod
    def fromGemmi(cls, fid:gemmi.Structure):
        if not isinstance(fid, gemmi.Structure):
            AssertionError ('Not a gemmi structure cannot use fromGemmi')
        
        prot = PDBParser.read_gemmi_struture(
                fid,
                hetatm=False,
                water=False)
        
        return cls(prot)

    def __init__(self, prot):
        self.__prot = prot
        
    @property
    def atomnumber(self):
        """Return array of atom numbers"""
        return self._get_property('number')

    @property
    def prot(self):
        return self.__prot

    @prot.setter
    def prot(self, prot):
        self.__prot = prot

    
    @property
    def bfacs(self):
        return np.asarray([a.temp_fac for a
                            in self.__prot.atomList])

    @property
    def chain_list(self):
        return self.prot.get_chain_list()

    @property
    def coor(self):
        """Return the coordinates"""
        return np.asarray([*zip(*[atom.get_pos_vector()for atom in self.prot.atomList])])

    def duplicate(self):
        """Duplicate the object"""
        protdupe = self.__prot.copy()
        structure = copy(self)
        structure.prot = protdupe
        return structure

    def _get_property(self, ptype):
        elements, ind = np.unique(
            [atom.elem for atom in self.prot.atomList], return_inverse=True
            )
        return np.asarray([getattr(ELEMENTS[capwords(e)], ptype) 
            for e in elements], dtype=np.float64)[ind]

    @property
    def mass(self):
        return self._get_property('mass')
    
    
    @property
    def filename(self):
        return str(Path(self.__prot.filename).resolve())
    
    @filename.setter
    def filename(self, fname):
        self.__prot.filename = fname

    def rmsd(self, structure):
        return np.sqrt(((self.coor - structure.coor) ** 2).mean() * 3)

    def rotate(self, rotmat):
        """Rotate atoms"""
     
        self.__prot.matrix_transform(rotmat)
    
    
    def combine(self, structure):
        self.__prot.add_structure_instance(structure.prot)

   
    @property
    def sequence(self):
        return np.asarray([atom.res for atom in self.prot.get_CAonly()])

    def translate(self, trans):
        """Translate atoms"""
        tx, ty, tz = trans
        self.prot.translate(tx, ty, tz)

    def tofile(self, fid=None, outtype = 'pdb'):
        """Write instance to PDB-file"""
        if fid is None:
            fid = self.filename
            
        if outtype == 'pdb':
            self.__prot.write_to_PDB(fid)

        elif outtype == 'mmcif':
            self.__prot.write_to_mmcif(fid)
            
        else:
            raise IOError('Filetype not recognized.')

    @property
    def rvdw(self):
        return self._get_property('vdwrad')
    
    @property
    def centre_of_mass(self):
        return np.array([x for x in self.prot.CoM])




def parse_mmcif(infile):
    if isinstance(infile, io.TextIOBase):
        pass
    elif isinstance(infile, str):
        infile = open(infile)
    else:
        raise TypeError("Input should either be a file or string.")

    atom_site = OrderedDict()
    with infile as f:
        for line in f:

            if line.startswith('_atom_site.'):
                words = line.split('.')
                atom_site[words[1].strip()] = []

            if line.startswith('ATOM'):
                words = line.split()
                for key, word in zip(atom_site, words):
                    atom_site[key].append(word)
    return atom_site


def mmcif_dict_to_array(atom_site):

    natoms = len(atom_site['id'])
    dtype = [('record', np.str_, 6), ('id', np.int32),
             ('name', np.str_, 4), ('alt', np.str_, 1),
             ('resn', np.str_, 4), ('chain', np.str_, 2),
             ('resi', np.int32), ('i', np.str_, 1), ('x', np.float64),
             ('y', np.float64), ('z', np.float64),
             ('q', np.float64), ('b', np.float64),
             ('e', np.str_, 2), ('charge', np.str_, 2),
             ('model', np.int32)]

    cifdata = np.zeros(natoms, dtype=dtype)
    cifdata['record'] = 'ATOM  '
    cifdata['id'] = atom_site['id']
    cifdata['name'] = atom_site['label_atom_id']
    cifdata['resn'] = atom_site['label_comp_id']
    cifdata['chain'] = atom_site['label_asym_id']
    cifdata['resi'] = atom_site['label_seq_id']
    cifdata['x'] = atom_site['Cartn_x']
    cifdata['y'] = atom_site['Cartn_y']
    cifdata['z'] = atom_site['Cartn_z']
    cifdata['q'] = atom_site['occupancy']
    cifdata['b'] = atom_site['B_iso_or_equiv']
    cifdata['e'] = atom_site['type_symbol']
    cifdata['charge'] = atom_site['pdbx_formal_charge']
    cifdata['model'] = atom_site['pdbx_PDB_model_num']
    return cifdata


class PDBParser(PDBParser):
    def __init__(self):
        pass

    @staticmethod
    def read_gemmi_struture(
            structure,
            hetatm=False,
            water=False,
    ):
        """Copy of PDBParser from TEMPy so I can read in gemmi structure"""
        filename = 'tempory_name.pdb'
    

        if not structure[0][0].name:
            structure = gemmi_helper_fns.name_nameless_chains(structure)

        if not hetatm:
            structure.remove_ligands_and_waters()
        if not water:
            structure.remove_waters()
        structure.remove_empty_chains()

        structure.setup_entities()
        structure.assign_label_seq_id()
        data_block = structure.make_mmcif_document().sole_block()

        return mmCIFParser._convertGEMMItoTEMPy(
                                            data_block,
                                            structure,
                                            filename,
                                            water=water,
                                            hetatm=hetatm,
                                            )
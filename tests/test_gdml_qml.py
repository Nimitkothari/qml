#!/usr/bin/env python2
from __future__ import print_function
import sys
sys.path.append("/home/andersx/dev/qml/fchl_gdml/build/lib.linux-x86_64-2.7")

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from time import time
import ast

import scipy
import scipy.stats

from copy import deepcopy

import numpy as np
from numpy.linalg import norm, inv
import pandas as pd

import qml
from qml.math import cho_solve
from qml.fchl import generate_fchl_representation
from qml.fchl import generate_displaced_fchl_representations

from qml.fchl import get_local_symmetric_kernels_fchl
from qml.fchl import get_local_kernels_fchl

from qml.fchl import get_local_hessian_kernels_fchl
from qml.fchl import get_local_symmetric_hessian_kernels_fchl

from qml.fchl import get_local_gradient_kernels_fchl

from qml.fchl import get_local_full_kernels_fchl
from qml.fchl import get_local_invariant_alphas_fchl

np.set_printoptions(linewidth=19999999999, suppress=True, edgeitems=10)


# SIGMAS = [1.28]
# SIZE = 3
# FORCE_KEY  = "mopac_forces"
# ENERGY_KEY = "mopac_energy"
# CSV_FILE = "data/01.csv"

# SIZE = 5
# FORCE_KEY = "forces"
# ENERGY_KEY = "om2_energy"
# CSV_FILE = "data/1a_1200.csv"

# SIGMAS = [0.32]
# SIZE = 6
# FORCE_KEY = "forces"
# ENERGY_KEY = "om2_energy"
# CSV_FILE = "data/2a_1200.csv"


# SIGMAS = [10.24]
# SIZE = 6
# FORCE_KEY  = "mopac_forces"
# ENERGY_KEY = "mopac_energy"
# CSV_FILE = "data/02.csv"

SIZE = 19
FORCE_KEY = "forces"
ENERGY_KEY = "om2_energy"
CSV_FILE = "data/molecule_300.csv"

TRAINING = 100
TEST     = 100

CUT_DISTANCE = 1e6
LLAMBDA = 1e-7
LLAMBDA_ENERGY = 1e-10
LLAMBDA_FORCE = 1e-7

SIGMAS = [0.01 * 2**i for i in range(20)]
# SIGMAS = [0.01 * 2**i for i in range(10)]
# SIGMAS = [0.01 * 2**i for i in range(10, 20)]
# SIGMAS = [10.24]
# SIGMAS = [100.0]
ENERGY_SCALE = 1.0 #/ SIZE
FORCE_SCALE = 1.0 #/ (SIZE / 3.0 * 2.0)

DX = 0.05

kernel_args={
    "cut_distance": CUT_DISTANCE, 
    "alchemy": "off",
    # "scale_distance": 1.0,
    # "d_width": 0.15,
    "two_body_power": 2.0,

    # "scale_angular": 0.5,
    "three_body_power": 1.0,
    # "t_width": np.pi/2,
}


def csv_to_molecular_reps(csv_filename, force_key="orca_forces", energy_key="orca_energy"):

    df = pd.read_csv(csv_filename)

    x = []
    f = []
    e = []
    distance = []

    disp_x = []

    max_atoms = max([len(ast.literal_eval(df["atomtypes"][i])) for i in range(TRAINING+TEST)])

    print("MAX ATOMS:", max_atoms)


    for i in range(len(df)):

        if i > TRAINING + TEST: break

        coordinates = np.array(ast.literal_eval(df["coordinates"][i]))

        dist = norm(coordinates[0] - coordinates[1])
        nuclear_charges = np.array(ast.literal_eval(df["nuclear_charges"][i]), dtype=np.int32)
        atomtypes = ast.literal_eval(df["atomtypes"][i])

        force = np.array(ast.literal_eval(df[force_key][i]))
        energy = df[energy_key][i]

        rep = generate_fchl_representation(coordinates, nuclear_charges, 
                size=max_atoms, cut_distance=CUT_DISTANCE)
        disp_rep = generate_displaced_fchl_representations(coordinates, nuclear_charges, 
                size=max_atoms, cut_distance=CUT_DISTANCE, dx=DX)

        distance.append(dist)
        x.append(rep)
        f.append(force)
        e.append(energy)

        disp_x.append(disp_rep)

    return np.array(x), f, e, distance, np.array(disp_x)

def get_full_kernel_fortran(Xall, Fall, Eall, Dall, dXall):

    Eall = np.array(Eall)
    Fall = np.array(Fall)

    X  = Xall[:TRAINING]
    dX = dXall[:TRAINING]
    F  = Fall[:TRAINING]
    E  = Eall[:TRAINING]
    D  = Dall[:TRAINING]
    
    Xs = Xall[-TEST:]
    dXs = dXall[-TEST:]
    Fs = Fall[-TEST:]
    Es = Eall[-TEST:]
    Ds = Dall[-TEST:]

    start = time()    
    K = get_local_full_kernels_fchl(X, dX, SIGMAS, dx=DX, **kernel_args)
    print("Elapsed time", start - time())

    Kt = K[:,TRAINING:,TRAINING:]
    Kt_local = K[:,:TRAINING,:TRAINING]
    Kt_energy = K[:,:TRAINING,TRAINING:]

    Ks          = get_local_hessian_kernels_fchl(     dX, dXs, SIGMAS, dx=DX, **kernel_args)
    Ks_energy   = get_local_gradient_kernels_fchl(  X,  dXs, SIGMAS, dx=DX, **kernel_args)
    
    Ks_energy2  = get_local_gradient_kernels_fchl(  Xs, dX,  SIGMAS, dx=DX, **kernel_args)
    Ks_local    = get_local_kernels_fchl(           X,  Xs,  SIGMAS,        **kernel_args)

    Y = np.array(F.flatten())
    Y = np.concatenate((E, Y))

    Fs = np.array(Fs.flatten())

    for i, sigma in enumerate(SIGMAS):

        C = deepcopy(K[i])
        
        for j in range(TRAINING):
            C[j,j] += LLAMBDA_ENERGY

        for j in range(TRAINING,K.shape[2]):
            C[j,j] += LLAMBDA_FORCE

        alpha = cho_solve(C, Y)
        beta = alpha[:TRAINING]
        gamma = alpha[TRAINING:]

        Fss = np.dot(np.transpose(Ks[i]), gamma) + np.dot(np.transpose(Ks_energy[i]), beta)
        Ft  = np.dot(np.transpose(Kt[i]), gamma) + np.dot(np.transpose(Kt_energy[i]), beta)

        Ess = np.dot(Ks_energy2[i], gamma) + np.dot(Ks_local[i].T, beta)
        Et  = np.dot(Kt_energy [i], gamma) + np.dot(Kt_local[i].T, beta)

        slope, intercept, r_value, p_value, std_err = scipy.stats.linregress(Fs.flatten(), Fss.flatten())
        print("TEST     FORCE    MAE = %10.4f     sigma = %10.4f  slope = %10.4f  intercept = %10.4f  r^2 = %9.6f" % \
                (np.mean(np.abs(Fss - Fs)), sigma, slope, intercept, r_value ))

        slope, intercept, r_value, p_value, std_err = scipy.stats.linregress(F.flatten(), Ft.flatten())
        print("TRAINING FORCE    MAE = %10.4f     sigma = %10.4f  slope = %10.4f  intercept = %10.4f  r^2 = %9.6f" % \
                (np.mean(np.abs(Ft.flatten() - F.flatten())), sigma, slope, intercept, r_value ))

        slope, intercept, r_value, p_value, std_err = scipy.stats.linregress(Es.flatten(), Ess.flatten())
        print("TEST     ENERGY   MAE = %10.4f     sigma = %10.4f  slope = %10.4f  intercept = %10.4f  r^2 = %9.6f" % \
                (np.mean(np.abs(Ess - Es)), sigma, slope, intercept, r_value ))

        slope, intercept, r_value, p_value, std_err = scipy.stats.linregress(E.flatten(), Et.flatten())
        print("TRAINING ENERGY   MAE = %10.4f     sigma = %10.4f  slope = %10.4f  intercept = %10.4f  r^2 = %9.6f" % \
                (np.mean(np.abs(Et - E)), sigma, slope, intercept, r_value ))

        plt.figure(figsize=(10,4.5))
        plt.subplot(121)
        plt.grid(True)
        plt.title("Forces, sigma = %10.2f" % sigma)
        plt.scatter(F.flatten(), Ft.flatten(), label="training")
        plt.scatter(Fs.flatten(), Fss.flatten(), label="test")
        plt.legend()
        plt.xlabel("True Gradient [kcal/mol/angstrom]")
        plt.ylabel("GP(E+F) Gradient [kcal/mol/angstrom]")

        plt.subplot(122)
        plt.title("Energy, sigma = %10.2f" % sigma)
        plt.grid(True)
        plt.scatter(E,  Et,    label="training" )
        plt.scatter(Es, Ess,   label="test")
        plt.xlabel("True Energy [kcal/mol]")
        plt.ylabel("GP(E+F) Energy [kcal/mol]")
        plt.legend()
        plt.tight_layout()

        plt.savefig("FULL_%f.png" % sigma)
        plt.savefig("FULL.png")
        plt.clf()
        plt.close('all')

def get_gdml_kernel_fortran(Xall, Fall, Eall, Dall, dXall):

    Eall = np.array(Eall)
    Fall = np.array(Fall)

    X = Xall[:TRAINING]
    dX = dXall[:TRAINING]
    F = Fall[:TRAINING]
    E = Eall[:TRAINING]
    D = Dall[:TRAINING]
    
    Xs = Xall[-TEST:]
    dXs = dXall[-TEST:]
    Fs = Fall[-TEST:]
    Es = Eall[-TEST:]
    Ds = Dall[-TEST:]

    K         = get_local_symmetric_hessian_kernels_fchl( dX,      SIGMAS, dx=DX, **kernel_args)
    Ks        = get_local_hessian_kernels_fchl(           dX, dXs, SIGMAS, dx=DX, **kernel_args)

    Kt_energy = get_local_gradient_kernels_fchl(        X,  dX,  SIGMAS, dx=DX, **kernel_args)
    Ks_energy = get_local_gradient_kernels_fchl(        Xs, dX,  SIGMAS, dx=DX, **kernel_args)
    
    Y = np.array(F.flatten())
    Fs = np.array(Fs.flatten())

    for i, sigma in enumerate(SIGMAS):

        C = deepcopy(K[i])

        C[np.diag_indices_from(C)] += LLAMBDA
        alpha = cho_solve(C, Y)

        Fss = np.dot(np.transpose(Ks[i]), alpha)
        Ft = np.dot(np.transpose(K[i]), alpha)

        Ess = np.dot(Ks_energy[i], alpha)
        Et  = np.dot(Kt_energy[i], alpha)

        intercept = np.mean(Et - E)

        Ess -= intercept
        Et -= intercept

        slope, intercept, r_value, p_value, std_err = scipy.stats.linregress(Fs.flatten(), Fss.flatten())
        print("TEST     FORCE    MAE = %10.4f     sigma = %10.4f  slope = %10.4f  intercept = %10.4f  r^2 = %9.6f" % \
                (np.mean(np.abs(Fss - Fs)), sigma, slope, intercept, r_value ))

        slope, intercept, r_value, p_value, std_err = scipy.stats.linregress(F.flatten(), Ft.flatten())
        print("TRAINING FORCE    MAE = %10.4f     sigma = %10.4f  slope = %10.4f  intercept = %10.4f  r^2 = %9.6f" % \
                (np.mean(np.abs(Ft.flatten() - F.flatten())), sigma, slope, intercept, r_value ))
        slope, intercept, r_value, p_value, std_err = scipy.stats.linregress(Es.flatten(), Ess.flatten())
        print("TEST     ENERGY   MAE = %10.4f     sigma = %10.4f  slope = %10.4f  intercept = %10.4f  r^2 = %9.6f" % \
                (np.mean(np.abs(Ess - Es)), sigma, slope, intercept, r_value ))

        slope, intercept, r_value, p_value, std_err = scipy.stats.linregress(E.flatten(), Et.flatten())
        print("TRAINING ENERGY   MAE = %10.4f     sigma = %10.4f  slope = %10.4f  intercept = %10.4f  r^2 = %9.6f" % \
                (np.mean(np.abs(Et - E)), sigma, slope, intercept, r_value ))

        plt.figure(figsize=(10,4.5))
        plt.subplot(121)
        plt.grid(True)
        plt.title("Forces, sigma = %10.2f" % sigma)
        plt.scatter(F.flatten(), Ft.flatten(), label="training")
        plt.scatter(Fs.flatten(), Fss.flatten(), label="test")
        plt.legend()
        plt.xlabel("True Gradient [kcal/mol/angstrom]")
        plt.ylabel("GDML Gradient [kcal/mol/angstrom]")

        plt.subplot(122)
        plt.title("Energy, sigma = %10.2f" % sigma)
        plt.grid(True)
        plt.scatter(E,  Et,    label="training" )
        plt.scatter(Es, Ess,   label="test")
        plt.xlabel("True Energy [kcal/mol]")
        plt.ylabel("GDML Energy [kcal/mol]")
        plt.legend()
        plt.tight_layout()

        plt.savefig("GDML_%f.png" % sigma)
        plt.savefig("GDML.png")
        plt.clf()
        plt.close('all')

def get_energy_kernel_fortran(Xall, Fall, Eall, Dall, dXall):

    Eall = np.array(Eall)
    Fall = np.array(Fall)

    X = Xall[:TRAINING]
    dX = dXall[:TRAINING]
    F = Fall[:TRAINING]
    E = Eall[:TRAINING]
    D = Dall[:TRAINING]
    
    Xs = Xall[-TEST:]
    dXs = dXall[-TEST:]
    Fs = Fall[-TEST:]
    Es = Eall[-TEST:]
    Ds = Dall[-TEST:]

    K         = get_local_symmetric_kernels_fchl(X,      SIGMAS, **kernel_args)
    Ks        = get_local_kernels_fchl(          X, Xs,  SIGMAS, **kernel_args)

    Kt_force = get_local_gradient_kernels_fchl(        X,  dX,  SIGMAS, dx=DX, **kernel_args)
    Ks_force = get_local_gradient_kernels_fchl(        X, dXs,  SIGMAS, dx=DX, **kernel_args)
    
    Y = np.array(F.flatten())
    Fs = np.array(Fs.flatten())



    for i, sigma in enumerate(SIGMAS):

        C = deepcopy(K[i])

        C[np.diag_indices_from(C)] += LLAMBDA
        alpha = cho_solve(C, E)

        Fss = np.dot(np.transpose(Ks_force[i]), alpha)
        Ft  = np.dot(np.transpose(Kt_force[i]), alpha)

        Ess = np.dot(np.transpose(Ks[i]), alpha)
        Et  = np.dot(K[i],  alpha)

        intercept = np.mean(Et - E)

        # Ess -= intercept
        # Et -= intercept

        slope, intercept, r_value, p_value, std_err = scipy.stats.linregress(Fs.flatten(), Fss.flatten())
        print("TEST     FORCE    MAE = %10.4f     sigma = %10.4f  slope = %10.4f  intercept = %10.4f  r^2 = %9.6f" % \
                (np.mean(np.abs(Fss - Fs)), sigma, slope, intercept, r_value ))

        slope, intercept, r_value, p_value, std_err = scipy.stats.linregress(F.flatten(), Ft.flatten())
        print("TRAINING FORCE    MAE = %10.4f     sigma = %10.4f  slope = %10.4f  intercept = %10.4f  r^2 = %9.6f" % \
               (np.mean(np.abs(Ft.flatten() - F.flatten())), sigma, slope, intercept, r_value ))
        
        slope, intercept, r_value, p_value, std_err = scipy.stats.linregress(Es.flatten(), Ess.flatten())
        print("TEST     ENERGY   MAE = %10.4f     sigma = %10.4f  slope = %10.4f  intercept = %10.4f  r^2 = %9.6f" % \
                (np.mean(np.abs(Ess - Es)), sigma, slope, intercept, r_value ))

        slope, intercept, r_value, p_value, std_err = scipy.stats.linregress(E.flatten(), Et.flatten())
        print("TRAINING ENERGY   MAE = %10.4f     sigma = %10.4f  slope = %10.4f  intercept = %10.4f  r^2 = %9.6f" % \
                (np.mean(np.abs(Et - E)), sigma, slope, intercept, r_value ))

        plt.figure(figsize=(10,4.5))
        plt.subplot(121)
        plt.grid(True)
        plt.title("Forces, sigma = %10.2f" % sigma)
        plt.scatter(F.flatten(), Ft.flatten(), label="training")
        plt.scatter(Fs.flatten(), Fss.flatten(), label="test")
        plt.legend()
        plt.xlabel("True Gradient [kcal/mol/angstrom]")
        plt.ylabel("GP(E) Gradient [kcal/mol/angstrom]")

        plt.subplot(122)
        plt.title("Energy, sigma = %10.2f" % sigma)
        plt.grid(True)
        plt.scatter(E,  Et,    label="training" )
        plt.scatter(Es, Ess,   label="test")
        plt.xlabel("True Energy [kcal/mol]")
        plt.ylabel("GP(E) Energy [kcal/mol]")
        plt.legend()
        plt.tight_layout()

        plt.savefig("ENERGY_%f.png" % sigma)
        plt.savefig("ENERGY.png")
        plt.clf()
        plt.close('all')


def get_invariant_kernel_fortran(Xall, Fall, Eall, Dall, dXall):

    Eall = np.array(Eall)
    Fall = np.array(Fall)

    X = Xall[:TRAINING]
    dX = dXall[:TRAINING]
    F = Fall[:TRAINING]
    E = Eall[:TRAINING]
    D = Dall[:TRAINING]
    
    Xs = Xall[-TEST:]
    dXs = dXall[-TEST:]
    Fs = Fall[-TEST:]
    Es = Eall[-TEST:]
    Ds = Dall[-TEST:]

    Ftrain = np.concatenate(F)
    print(Ftrain.shape)

    alphas      = get_local_invariant_alphas_fchl(X, dX, Ftrain, SIGMAS, dx=DX, **kernel_args)
    
    Kt_force = get_local_gradient_kernels_fchl(        X,  dX,   SIGMAS, dx=DX, **kernel_args)
    Ks_force = get_local_gradient_kernels_fchl(        X, dXs,   SIGMAS, dx=DX, **kernel_args)
    
    Kt_energy = get_local_kernels_fchl(X, X,   SIGMAS, **kernel_args)
    Ks_energy = get_local_kernels_fchl(X, Xs,  SIGMAS, **kernel_args)
    
    Y = np.array(F.flatten())

    F = np.concatenate(F)
    Fs = np.concatenate(Fs)


    for i, sigma in enumerate(SIGMAS):

        Kt = np.zeros((alphas[i].shape[0],Kt_force[i,:,:].shape[1]/3)) 
        Ks = np.zeros((alphas[i].shape[0],Ks_force[i,:,:].shape[1]/3)) 

        Ft  = np.zeros((Kt_force[i,:,:].shape[1]/3,3))
        Fss = np.zeros((Ks_force[i,:,:].shape[1]/3,3))

        for xyz in range(3):

            for j in range(TRAINING):
                Kt[j*SIZE:(j+1)*SIZE,:] = Kt_force[i,j,xyz::3]
                Ks[j*SIZE:(j+1)*SIZE,:] = Ks_force[i,j,xyz::3]
            
            Ft[:,xyz]  = np.dot(Kt.T, alphas[i])
            Fss[:,xyz] = np.dot(Ks.T, alphas[i])

        Kt_e = np.zeros((alphas[i].shape[0],TRAINING)) 
        Ks_e = np.zeros((alphas[i].shape[0],TEST))

        for j in range(TRAINING):
            for k in range(TRAINING):
                Kt_e[j*SIZE:(j+1)*SIZE,k] = Kt_energy[i,j,k]
            for k in range(TEST):
                Ks_e[j*SIZE:(j+1)*SIZE,k] = Ks_energy[i,j,k]

        Ess = np.dot(Ks_e.T, alphas[i])
        Et  = np.dot(Kt_e.T,  alphas[i])
        
        intercept = np.mean(Et - E)

        Ess -= intercept
        Et -= intercept

        slope, intercept, r_value, p_value, std_err = scipy.stats.linregress(Fs.flatten(), Fss.flatten())
        print("TEST     FORCE    MAE = %10.4f     sigma = %10.4f  slope = %10.4f  intercept = %10.4f  r^2 = %9.6f" % \
                (np.mean(np.abs(Fss - Fs)), sigma, slope, intercept, r_value ))

        slope, intercept, r_value, p_value, std_err = scipy.stats.linregress(F.flatten(), Ft.flatten())
        print("TRAINING FORCE    MAE = %10.4f     sigma = %10.4f  slope = %10.4f  intercept = %10.4f  r^2 = %9.6f" % \
               (np.mean(np.abs(Ft.flatten() - F.flatten())), sigma, slope, intercept, r_value ))
        
        slope, intercept, r_value, p_value, std_err = scipy.stats.linregress(Es.flatten(), Ess.flatten())
        print("TEST     ENERGY   MAE = %10.4f     sigma = %10.4f  slope = %10.4f  intercept = %10.4f  r^2 = %9.6f" % \
                (np.mean(np.abs(Ess - Es)), sigma, slope, intercept, r_value ))

        slope, intercept, r_value, p_value, std_err = scipy.stats.linregress(E.flatten(), Et.flatten())
        print("TRAINING ENERGY   MAE = %10.4f     sigma = %10.4f  slope = %10.4f  intercept = %10.4f  r^2 = %9.6f" % \
                (np.mean(np.abs(Et - E)), sigma, slope, intercept, r_value ))

#    #     plt.figure(figsize=(10,4.5))
#    #     plt.subplot(121)
#    #     plt.grid(True)
#    #     plt.title("Forces, sigma = %10.2f" % sigma)
#    #     plt.scatter(F.flatten(), Ft.flatten(), label="training")
#    #     plt.scatter(Fs.flatten(), Fss.flatten(), label="test")
#    #     plt.legend()
#    #     plt.xlabel("True Gradient [kcal/mol/angstrom]")
#    #     plt.ylabel("GP(E) Gradient [kcal/mol/angstrom]")
#
#    #     plt.subplot(122)
#    #     plt.title("Energy, sigma = %10.2f" % sigma)
#    #     plt.grid(True)
#    #     plt.scatter(E,  Et,    label="training" )
#    #     plt.scatter(Es, Ess,   label="test")
#    #     plt.xlabel("True Energy [kcal/mol]")
#    #     plt.ylabel("GP(E) Energy [kcal/mol]")
#    #     plt.legend()
#    #     plt.tight_layout()
#
#    #     plt.savefig("ENERGY_%f.png" % sigma)
#    #     plt.savefig("ENERGY.png")
#    #     plt.clf()
#    #     plt.close('all')

if __name__ == "__main__":
    
    Xall, Fall, Eall, Dall, dXall = csv_to_molecular_reps(CSV_FILE,
                                force_key=FORCE_KEY, energy_key=ENERGY_KEY)
    # get_gdml_kernel_fortran(Xall, Fall, Eall, Dall, dXall)
    # get_full_kernel_fortran(Xall, Fall, Eall, Dall, dXall)
    get_energy_kernel_fortran(Xall, Fall, Eall, Dall, dXall)
    # get_invariant_kernel_fortran(Xall, Fall, Eall, Dall, dXall)

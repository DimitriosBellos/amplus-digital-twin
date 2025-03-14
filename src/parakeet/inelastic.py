#
# Copyright (C) 2019 Diamond Light Source and Rosalind Franklin Institute
#
# Author: James Parkhurst
#
# This code is distributed under the GPLv3 license, a copy of
# which is included in the root directory of this package.
#
import numpy as np
import parakeet.landau
import scipy.signal
from math import sqrt, pi, cos, exp, log, ceil, floor


def effective_thickness(shape, angle):
    """
    Compute the effective thickness

    """
    TINY = 1e-10
    if shape["type"] == "cube":
        D0 = shape["cube"]["length"]
        thickness = D0 / (cos(pi * angle / 180.0) + TINY)
    elif shape["type"] == "cuboid":
        D0 = shape["cuboid"]["length_z"]
        thickness = D0 / (cos(pi * angle / 180.0) + TINY)
    elif shape["type"] == "cylinder":
        thickness = shape["cylinder"]["radius"] * 2
    return thickness


def zero_loss_fraction(shape, angle):
    """
    Compute the zero loss fraction

    """
    thickness = effective_thickness(shape, angle)
    mean_free_path = 3150  # A for Amorphous Ice at 300 keV
    electron_fraction = exp(-thickness / mean_free_path)
    return electron_fraction


def mp_loss_fraction(shape, angle):
    """
    Compute the inelastic fraction

    """
    thickness = effective_thickness(shape, angle)
    mean_free_path = 3150  # A for Amorphous Ice at 300 keV
    electron_fraction = exp(-thickness / mean_free_path)
    return 1.0 - electron_fraction


def fraction_of_electrons(shape, angle, model=None):
    """
    Compute the fraction of electrons

    """
    if model is None:
        fraction = 1.0
    elif model == "zero_loss":
        fraction = zero_loss_fraction(shape, angle)
    elif model == "mp_loss":
        fraction = mp_loss_fraction(shape, angle)
    elif model == "unfiltered":
        fraction = 1.0
    elif model == "cc_corrected":
        fraction = 1.0
    return fraction


def most_probable_loss(energy, shape, angle):
    """
    Compute the MPL peak and sigma

    Params:
        energy (float): Beam energy in keV

    Returns:
        tuple: (peak, sigma) of the energy loss distribution (eV)

    """
    thickness = effective_thickness(shape, angle)
    thickness = min(thickness, 100000)  # Maximum 10 um - to avoid issues at high tilt
    peak, fwhm = parakeet.landau.mpl_and_fwhm(energy, thickness)
    return peak, fwhm / (2 * sqrt(2 * log(2)))


class EnergyFilterOptimizer(object):
    """
    A simple class to find the optimal energy filter placement when trying to
    take into account the inelastic scattering component

    """

    def __init__(self, energy_spread=0.8, dE_min=-10, dE_max=200, dE_step=0.01):
        """
        Initialise the class

        Params:
            energy_spread (float): The energy spread (eV)
            dE_min (float): The minimum energy loss (eV)
            dE_max (float): The maximum energy loss (eV)
            dE_step (float): The energy loss step (eV)

        """

        # Save the energy spread
        self.energy_spread = energy_spread  # eV

        # Save an instance of the landau distribution class
        self.landau = parakeet.landau.Landau()

        # Set the energy losses to consider
        self.dE_min = dE_min
        self.dE_max = dE_max
        self.dE_step = dE_step

    def __call__(self, energy, thickness, filter_width=None):
        """
        Compute the optimum position for the energy filter

        Params:
            energy (float): The beam energy (eV)
            thickness (float): The sample thickness (A)
            filter_width (float): The energy filter width (eV)

        Returns:
            float: The optimal position to maximum number of electrons (eV)

        """

        # Check the input
        assert energy > 0
        assert thickness > 0

        # The energy loss distribution
        dE, distribution = self.energy_loss_distribution(energy, thickness)

        # Compute optimum given the position and filter width
        if filter_width is None:
            position = np.sum(dE * distribution) / np.sum(dE)
        else:
            size = len(distribution)
            kernel_size = filter_width / self.dE_step
            ks = kernel_size / 2
            kx = np.arange(-size // 2, size // 2 + 1)
            kernel = np.exp(-0.5 * (kx / ks) ** 80)
            kernel = kernel / np.sum(kernel)
            num = scipy.signal.fftconvolve(distribution, kernel, mode="same")
            position = dE[np.argmax(num)]

        # Return the filter position
        return position

    def elastic_fraction(self, energy, thickness):
        """
        Compute the elastic electron fraction

        Params:
            energy (float): The beam energy (eV)
            thickness (float): The sample thickness (A)

        Returns:
            float: The elastic electron fraction

        """
        # Compute the fractions for the zero loss and energy losses
        mean_free_path = 3150  # A for Amorphous Ice at 300 keV
        return exp(-thickness / mean_free_path)

    def energy_loss_distribution(self, energy, thickness):
        """
        Compute the energy loss distribution

        Params:
            energy (float): The beam energy (eV)
            thickness (float): The sample thickness (A)

        Returns:
            (array, array): dE (ev) and the energy loss distribution

        """

        # The energy losses to consider
        dE = np.arange(self.dE_min, self.dE_max, self.dE_step, dtype="float64")

        # The energy loss distribution
        energy_loss_distribution = self.landau(dE, energy, thickness)
        energy_loss_distribution /= self.dE_step * np.sum(energy_loss_distribution)

        # The zero loss distribution
        zero_loss_distribution = (1.0 / sqrt(pi * self.energy_spread**2)) * np.exp(
            -(dE**2) / self.energy_spread**2
        )

        # Compute the fractions for the zero loss and energy losses
        elastic_fraction = self.elastic_fraction(energy, thickness)

        # Return the distribution
        distribution = (
            elastic_fraction * zero_loss_distribution
            + (1 - elastic_fraction) * energy_loss_distribution
        )
        return dE, distribution

    def compute_elastic_component(self, energy, thickness, position, filter_width):
        """
        Compute the elastic fraction and energy spread

        Params:
            energy (float): The beam energy (eV)
            thickness (float): The sample thickness (A)
            position (float): The filter position (eV)
            filter_width (float): The energy filter width (eV)

        Returns:
            float, float: The electron fraction and energy spread (eV)

        """

        # The energy losses to consider
        dE = np.arange(self.dE_min, self.dE_max, self.dE_step)

        # The zero loss distribution
        P = (1.0 / sqrt(pi * self.energy_spread**2)) * np.exp(
            -(dE**2) / self.energy_spread**2
        )
        C = self.dE_step * np.cumsum(P)

        # Compute the fractions for the zero loss and energy losses
        fraction = self.elastic_fraction(energy, thickness)

        # Compute the number of electrons and the sigma
        if filter_width is not None:
            dE0 = position - filter_width / 2.0
            dE1 = position + filter_width / 2.0
            x0 = int(floor((dE0 - self.dE_min) / self.dE_step))
            x1 = int(ceil((dE1 - self.dE_min) / self.dE_step))
            x0 = max(x0, 0)
            x1 = min(x1, len(P) - 1)
            assert x1 > x0
            fraction *= C[x1] - C[x0]
            P = P[x0:x1]
            dE = dE[x0:x1]

        # Compute the spread
        if len(P) > 0 and np.sum(P) > 0:
            dE_mean = np.sum(P * dE) / np.sum(P)
            spread = sqrt(np.sum(P * (dE - dE_mean) ** 2) / np.sum(P)) * sqrt(2)
        else:
            spread = 0

        # Return the fraction and spread
        return fraction, spread

    def compute_inelastic_component(self, energy, thickness, position, filter_width):
        """
        Compute the inelastic fraction and energy spread

        Params:
            energy (float): The beam energy (eV)
            thickness (float): The sample thickness (A)
            position (float): The filter position (eV)
            filter_width (float): The energy filter width (eV)

        Returns:
            float, float: The electron fraction and energy spread (eV)

        """

        # The energy losses to consider
        dE = np.arange(self.dE_min, self.dE_max, self.dE_step)

        # The energy loss distribution
        P = self.landau(dE, energy, thickness)
        P /= self.dE_step * np.sum(P)
        C = np.cumsum(P) * self.dE_step

        # Compute the fractions for the zero loss and energy losses
        fraction = 1 - self.elastic_fraction(energy, thickness)

        # Compute the number of electrons and the sigma
        if filter_width is not None:
            dE0 = position - filter_width / 2.0
            dE1 = position + filter_width / 2.0
            x0 = int(floor((dE0 - self.dE_min) / self.dE_step))
            x1 = int(ceil((dE1 - self.dE_min) / self.dE_step))
            x0 = max(x0, 0)
            x1 = min(x1, len(P) - 1)
            assert x1 > x0
            fraction *= C[x1] - C[x0]
            P = P[x0:x1]
            dE = dE[x0:x1]

        # Compute the spread
        if len(P) > 0 and np.sum(P) > 0:
            peak, fwhm = parakeet.landau.mpl_and_fwhm(energy / 1000, thickness)
            sigma = fwhm / (2 * sqrt(2 * log(2)))

            # This is a hack to compute the variance because the heavy tail of
            # the landau distribution makes the variance undefined and this
            # causes problems for large filter sizes. There is probably a
            # better way to do this so maybe should look at fixing.
            P *= np.exp(-0.5 * (dE - peak) ** 2 / (2 * sigma) ** 2)

            P /= np.sum(P)
            dE_mean = np.sum(P * dE) / np.sum(P)
            spread = sqrt(np.sum(P * (dE - dE_mean) ** 2) / np.sum(P)) * sqrt(2)
        else:
            spread = 0

        # Return the fraction and spread
        return fraction, spread

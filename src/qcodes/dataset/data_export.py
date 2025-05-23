from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import numpy.typing as npt
from typing_extensions import TypedDict

from qcodes.utils import list_of_data_to_maybe_ragged_nd_array

if TYPE_CHECKING:
    from qcodes.dataset.data_set_protocol import DataSetProtocol
    from qcodes.dataset.descriptions.param_spec import ParamSpecBase

log = logging.getLogger(__name__)


class DSPlotData(TypedDict):
    """
    The dictionary used to represent data for use within `plot_dataset`
    """

    name: str
    unit: str
    label: str
    data: npt.NDArray
    shape: tuple[int, ...] | None


def _get_data_from_ds(ds: DataSetProtocol) -> list[list[DSPlotData]]:
    dependent_parameters: tuple[ParamSpecBase, ...] = tuple(
        ds.description.interdeps.dependencies.keys()
    )

    all_data = ds.cache.data()

    parameter_data = {ps.name: all_data[ps.name] for ps in dependent_parameters}

    output = []

    for dep_name, data_dict in parameter_data.items():
        data_dicts_list = []

        dependent = ds.description.interdeps[dep_name]
        dependencies = ds.description.interdeps.dependencies[dependent]

        for param_spec_base in (*dependencies, dependent):
            my_data_dict: DSPlotData = {
                "name": param_spec_base.name,
                "unit": param_spec_base.unit,
                "label": param_spec_base.label,
                "data": data_dict[param_spec_base.name],
                "shape": None,
            }
            data_dicts_list.append(my_data_dict)

        if ds.description.shapes is not None:
            data_dicts_list[-1]["shape"] = ds.description.shapes.get(dependent.name)

        output.append(data_dicts_list)

    return output


def _all_steps_multiples_of_min_step(rows: npt.NDArray) -> bool:
    """
    Are all steps integer multiples of the smallest step?
    This is used in determining whether the setpoints correspond
    to a regular grid

    Args:
        rows: the output of _rows_from_datapoints

    Returns:
        The answer to the question

    """

    steps_list: list[npt.NDArray] = []
    for row in rows:
        # TODO: What is an appropriate precision?
        steps_list += list(np.unique(np.diff(row).round(decimals=15)))

    steps = np.unique(steps_list)
    remainders = np.mod(steps[1:] / steps[0], 1)

    # TODO: What are reasonable tolerances for allclose?
    asmoms = bool(np.allclose(remainders, np.zeros_like(remainders)))

    return asmoms


def _rows_from_datapoints(inputsetpoints: npt.NDArray) -> npt.NDArray:
    """
    Cast the (potentially) unordered setpoints into rows
    of sorted, unique setpoint values. Because of the way they are ordered,
    these rows do not necessarily correspond to actual rows of the scan,
    but they can nonetheless be used to identify certain scan types

    Args:
        inputsetpoints: The raw setpoints as a one-dimensional array

    Returns:
        A ndarray of the rows

    """

    rows = []
    setpoints = inputsetpoints.copy()

    # first check if there is only one unique array in which case we can avoid the
    # potentially slow loop below
    temp, inds, count = np.unique(setpoints, return_index=True, return_counts=True)
    num_repeats_array = np.unique(count)
    if len(num_repeats_array) == 1 and count.sum() == len(inputsetpoints):
        return np.tile(temp, (num_repeats_array[0], 1))
    else:
        rows.append(temp)
        setpoints = np.delete(setpoints, inds)

    while len(setpoints) > 0:
        temp, inds = np.unique(setpoints, return_index=True)
        rows.append(temp)
        setpoints = np.delete(setpoints, inds)

    return list_of_data_to_maybe_ragged_nd_array(rows)


def _all_in_group_or_subgroup(rows: npt.NDArray) -> bool:
    """
    Detects whether the setpoints correspond to two groups of
    of identical rows, one being contained in the other.

    This is the test for whether the setpoints correspond to a
    rectangular sweep. It allows for a single rectangular hole
    in the setpoint grid, thus allowing for an interrupted sweep.
    Note that each axis needs NOT be equidistantly spaced.

    Args:
        rows: The output from _rows_from_datapoints

    Returns:
        A boolean indicating whether the setpoints meet the
            criterion

    """

    groups = 1
    comp_to = rows[0]

    aigos = True
    switchindex = 0

    for rowind, row in enumerate(rows[1:]):
        if np.array_equal(row, comp_to):
            continue
        else:
            groups += 1
            comp_to = row
            switchindex = rowind
            if groups > 2:
                aigos = False
                break

    # if there are two groups, check that the rows of one group
    # are all contained in the rows of the other
    if aigos and switchindex > 0:
        for row in rows[1 + switchindex :]:
            if sum(r in rows[0] for r in row) != len(row):
                aigos = False
                break

    return aigos


def _strings_as_ints(inputarray: npt.NDArray) -> npt.NDArray:
    """
    Return an integer-valued array version of a string-valued array. Maps, e.g.
    array(['a', 'b', 'c', 'a', 'c']) to array([0, 1, 2, 0, 2]). Useful for
    numerical setpoint analysis

    Args:
        inputarray: A 1D array of strings

    """
    newdata = np.zeros(len(inputarray))
    for n, word in enumerate(np.unique(inputarray)):
        newdata += (inputarray == word).astype(int) * n
    return newdata


def get_1D_plottype(xpoints: npt.NDArray, ypoints: npt.NDArray) -> str:
    """
    Determine plot type for a 1D plot by inspecting the data

    Possible plot types are:
    * '1D_bar' - bar plot
    * '1D_point' - scatter plot
    * '1D_line' - line plot

    Args:
        xpoints: The x-axis values
        ypoints: The y-axis values

    Returns:
        Determined plot type as a string

    """

    if isinstance(xpoints[0], str) and not isinstance(ypoints[0], str):
        if len(xpoints) == len(np.unique(xpoints)):
            return "1D_bar"
        else:
            return "1D_point"
    if isinstance(xpoints[0], str) or isinstance(ypoints[0], str):
        return "1D_point"
    else:
        return datatype_from_setpoints_1d(xpoints)


def datatype_from_setpoints_1d(setpoints: npt.NDArray) -> str:
    """
    Figure out what type of visualisation is proper for the
    provided setpoints.

    The type is:
        * '1D_point' (scatter plot) when all setpoints are identical
        * '1D_line' otherwise

    Args:
        setpoints: The x-axis values

    Returns:
        A string representing the plot type as described above

    """
    if np.allclose(setpoints, setpoints[0]):
        return "1D_point"
    else:
        return "1D_line"


def get_2D_plottype(
    xpoints: npt.NDArray, ypoints: npt.NDArray, zpoints: npt.NDArray
) -> str:
    """
    Determine plot type for a 2D plot by inspecting the data

    Plot types are:
    * '2D_grid' - colormap plot for data that is on a grid
    * '2D_equidistant' - colormap plot for data that is on equidistant grid
    * '2D_scatter' - scatter plot
    * '2D_unknown' - returned in case the data did not match any criteria of the
    other plot types

    Args:
        xpoints: The x-axis values
        ypoints: The y-axis values
        zpoints: The z-axis (colorbar) values

    Returns:
        Determined plot type as a string

    """

    plottype = datatype_from_setpoints_2d(xpoints, ypoints)
    return plottype


def datatype_from_setpoints_2d(xpoints: npt.NDArray, ypoints: npt.NDArray) -> str:
    """
    For a 2D plot, figure out what kind of visualisation we can use
    to display the data.

    Plot types are:
    * '2D_point' - all setpoint are the same in each direction; one point
    * '2D_grid' - colormap plot for data that is on a grid
    * '2D_equidistant' - colormap plot for data that is on equidistant grid
    * '2D_scatter' - scatter plot
    * '2D_unknown' - returned in case the data did not match any criteria of the
    other plot types

    Args:
        xpoints: The x-axis values
        ypoints: The y-axis values

    Returns:
        A string with the name of the determined plot type

    """
    # We represent categorical data as integer-valued data
    if isinstance(xpoints[0], str):
        xpoints = _strings_as_ints(xpoints)
    if isinstance(ypoints[0], str):
        ypoints = _strings_as_ints(ypoints)

    # First check whether all setpoints are identical along
    # any dimension
    x_all_the_same = np.allclose(xpoints, xpoints[0])
    y_all_the_same = np.allclose(ypoints, ypoints[0])

    if x_all_the_same or y_all_the_same:
        return "2D_point"

    # Now check if this is a simple rectangular sweep,
    # possibly interrupted in the middle of one row

    xrows = _rows_from_datapoints(xpoints)
    yrows = _rows_from_datapoints(ypoints)

    x_check = _all_in_group_or_subgroup(xrows)
    y_check = _all_in_group_or_subgroup(yrows)

    x_check = x_check and (len(xrows[0]) == len(yrows))
    y_check = y_check and (len(yrows[0]) == len(xrows))

    # this is the check that we are on a "simple" grid
    if y_check and x_check:
        return "2D_grid"

    x_check = _all_steps_multiples_of_min_step(xrows)
    y_check = _all_steps_multiples_of_min_step(yrows)

    # this is the check that we are on an equidistant grid
    if y_check and x_check:
        return "2D_equidistant"

    return "2D_unknown"


def reshape_2D_data(
    x: npt.NDArray, y: npt.NDArray, z: npt.NDArray
) -> tuple[npt.NDArray, npt.NDArray, npt.NDArray]:
    xrow = np.array(_rows_from_datapoints(x)[0])
    yrow = np.array(_rows_from_datapoints(y)[0])
    nx = len(xrow)
    ny = len(yrow)

    # potentially slow method of filling in the data, should be optimised
    log.debug("Sorting 2D data onto grid")

    if isinstance(z[0], str):
        z_to_plot = np.full((ny, nx), "", dtype=z.dtype)
    else:
        z_to_plot = np.full((ny, nx), np.nan)
    x_index = np.zeros_like(x, dtype=np.dtype(np.int_))
    y_index = np.zeros_like(y, dtype=np.dtype(np.int_))
    for i, xval in enumerate(xrow):
        x_index[np.where(x == xval)[0]] = i
    for i, yval in enumerate(yrow):
        y_index[np.where(y == yval)[0]] = i

    z_to_plot[y_index, x_index] = z

    return xrow, yrow, z_to_plot

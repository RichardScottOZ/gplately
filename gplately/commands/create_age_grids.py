#
#    Copyright (C) 2024 The University of Sydney, Australia
#
#    This program is free software; you can redistribute it and/or modify it under
#    the terms of the GNU General Public License, version 2, as published by
#    the Free Software Foundation.
#
#    This program is distributed in the hope that it will be useful, but WITHOUT
#    ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
#    FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
#    for more details.
#
#    You should have received a copy of the GNU General Public License along
#    with this program; if not, write to Free Software Foundation, Inc.,
#    51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#

import argparse
import datetime
import logging
import multiprocessing
import time
import warnings
from typing import Optional, Sequence, Union

from plate_model_manager import PlateModel, PlateModelManager

from gplately import PlateReconstruction, PlotTopologies, SeafloorGrid

from ..pygplates import FeatureCollection as gFeatureCollection
from ..pygplates import FeaturesFunctionArgument
from ..pygplates import RotationModel as gRotationModel

logger = logging.getLogger("gplately")


def add_parser(parser: argparse.ArgumentParser):
    """add command line argument parser"""

    agegrid_cmd = parser.add_parser(
        "agegrid",
        aliases=("ag",),
        help=__description__,
        add_help=True,
        description=__description__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # agegrid command arguments
    agegrid_cmd.set_defaults(func=_run_create_agegrids)
    agegrid_cmd.add_argument(
        metavar="INPUT_FILE",
        nargs="*",
        help="input reconstruction files, including rotation files and topology files",
        dest="input_filenames",
    )
    agegrid_cmd.add_argument(
        metavar="OUTPUT_DIR",
        help="output directory",
        dest="output_dir",
    )
    agegrid_cmd.add_argument(
        "-m",
        "--model",
        metavar="MODEL_NAME",
        help="reconstruction model name",
        dest="model_name",
        default=None,
    )
    agegrid_cmd.add_argument(
        "-c",
        "--continents",
        metavar="CONTINENTS_FILE",
        nargs="*",
        help="input continental polygons files",
        dest="continents_filenames",
        default=None,
    )
    agegrid_cmd.add_argument(
        "-r",
        "--resolution",
        metavar="RESOLUTION",
        type=float,
        help="grid resolution (degrees); default: 0.1",
        default=0.1,
        dest="grid_spacing",
    )
    agegrid_cmd.add_argument(
        "--refinement-levels",
        metavar="LEVELS",
        type=int,
        help="mesh refinement levels; default: 5",
        default=5,
        dest="refinement_levels",
    )
    agegrid_cmd.add_argument(
        "--ridge-sampling",
        metavar="RESOLUTION",
        type=float,
        help="MOR sampling resolution (degrees); default: 0.5",
        default=0.5,
        dest="ridge_sampling",
    )
    agegrid_cmd.add_argument(
        "--initial-spreadrate",
        metavar="SPREADRATE",
        type=float,
        help="initial ocean spreading rate (km/Myr); default: 75",
        default=75,
        dest="initial_spreadrate",
    )
    agegrid_cmd.add_argument(
        "-e",
        "--min-time",
        metavar="MIN_TIME",
        type=float,
        help="minimum time (Ma); default: 0",
        default=0,
        dest="min_time",
    )
    agegrid_cmd.add_argument(
        "-s",
        "--max-time",
        metavar="MAX_TIME",
        type=float,
        help="maximum time (Ma); default: 0",
        default=0,
        dest="max_time",
    )
    agegrid_cmd.add_argument(
        "-j",
        "--n_jobs",
        help="number of processes to use; default: use all CPU available",
        metavar="N_JOBS",
        default=None,
        dest="n_jobs",
    )
    agegrid_cmd.add_argument(
        "-f",
        "--file-collection",
        help="file collection name (optional)",
        metavar="NAME",
        default=None,
        dest="file_collection",
    )
    agegrid_cmd.add_argument(
        "-u",
        "--include-unmasked",
        help="create unmasked grids in addition to masked ones",
        action="store_true",
        dest="unmasked",
    )


__description__ = """Create age grids for a plate model.

Example usage: 
    - gplately ag output -m merdith2021 -e 0 -s 10
    - gplately ag plate-model-repo/muller2019/Rotations/Muller_etal_2019_CombinedRotations.rot plate-model-repo/muller2019/Topologies/Muller_etal_2019_PlateBoundaries_DeformingNetworks.gpmlz output -c plate-model-repo/muller2019/ContinentalPolygons/Global_EarthByte_GPlates_PresentDay_ContinentalPolygons_2019_v1.shp -e 0 -s 10
"""


def create_agegrids(
    model_name: str,
    input_filenames: Union[str, Sequence[str]],
    continents_filenames: Union[str, Sequence[str]],
    output_dir: str,
    min_time: float,
    max_time: float,
    ridge_time_step: float = 1,
    n_jobs: int = 1,
    refinement_levels: int = 5,
    grid_spacing: float = 0.1,
    ridge_sampling: float = 0.5,
    initial_spreadrate: float = 75,
    file_collection: Optional[str] = None,
    unmasked: bool = False,
) -> None:
    """Create age grids for a plate model."""

    if model_name:
        try:
            plate_model = PlateModelManager().get_model(
                model_name, data_dir="plate-model-repo"
            )
        except:
            plate_model = PlateModel(
                model_name, data_dir="plate-model-repo", readonly=True
            )

        rotation_files = plate_model.get_rotation_model()
        topology_files = plate_model.get_topologies()
        continent_files = plate_model.get_layer("ContinentalPolygons")
        if "Cratons" in plate_model.get_avail_layers():
            continent_files += plate_model.get_layer("Cratons")

    else:
        rotation_files = []
        topology_files = []
        for fn in input_filenames:
            features = FeaturesFunctionArgument([fn]).get_features()
            if len(features) > 0:
                if (
                    features[0].get_feature_type().to_qualified_string()
                    == "gpml:TotalReconstructionSequence"
                ):
                    rotation_files.append(fn)
                else:
                    topology_files.append(fn)

        continent_files = continents_filenames

    rotations = gRotationModel(rotation_files)
    topologies = gFeatureCollection.from_file_list(topology_files)
    continents = gFeatureCollection.from_file_list(continent_files)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ImportWarning)
        reconstruction = PlateReconstruction(
            rotation_model=rotations,
            topology_features=topologies,
        )
        gplot = PlotTopologies(
            reconstruction,
            continents=continents,
        )

        grid = SeafloorGrid(
            reconstruction,
            gplot,
            min_time=min_time,
            max_time=max_time,
            save_directory=output_dir,
            ridge_time_step=ridge_time_step,
            refinement_levels=refinement_levels,
            grid_spacing=grid_spacing,
            ridge_sampling=ridge_sampling,
            initial_ocean_mean_spreading_rate=initial_spreadrate,
            file_collection=file_collection,
        )

        # grid.reconstruct_by_topologies()
        grid.reconstruct_by_topological_model()
        for val in ("SEAFLOOR_AGE", "SPREADING_RATE"):
            grid.save_netcdf_files(val, unmasked=unmasked, nprocs=n_jobs)


def _run_create_agegrids(args):
    n_jobs = args.n_jobs
    if not n_jobs:
        try:
            n_jobs = multiprocessing.cpu_count()
        except NotImplementedError:
            n_jobs = 1
    start = time.time()

    create_agegrids(
        model_name=args.model_name,
        input_filenames=args.input_filenames,
        continents_filenames=args.continents_filenames,
        output_dir=args.output_dir,
        min_time=args.min_time,
        max_time=args.max_time,
        n_jobs=n_jobs,
        refinement_levels=args.refinement_levels,
        grid_spacing=args.grid_spacing,
        ridge_sampling=args.ridge_sampling,
        initial_spreadrate=args.initial_spreadrate,
        file_collection=args.file_collection,
        unmasked=args.unmasked,
    )

    end = time.time()
    hours_minutes_seconds = str(datetime.timedelta(seconds=end - start)).split(":")
    logger.info(
        f"Completed creating age grids in {hours_minutes_seconds[0]} Hours, {hours_minutes_seconds[1]} Minutes, {hours_minutes_seconds[2].split('.')[0]} Seconds "
    )

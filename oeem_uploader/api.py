from .requester import Requester
from .uploaders import ProjectUploader
from .uploaders import ProjectAttributeUploader
from .uploaders import ProjectAttributeKeyUploader
from .uploaders import ConsumptionMetadataUploader
from . import constants
from datetime import date, datetime
from eemeter.location import Location
from eemeter.evaluation import Period
from eemeter.consumption import ConsumptionData
from eemeter.project import Project
import pandas as pd
import pytz
import re

def upload_dataset(project_csv, consumption_csv, url, access_token, verbose=True):
    """
    Main entrypoint - takes in formatted project and consumption data and
    uploads it to the given url.
    """
    project_df, consumption_df = _convert_to_dataframes(project_csv,
                                                        consumption_csv)

    requester = Requester(url, access_token)
    project_attribute_key_uploader = ProjectAttributeKeyUploader(requester, verbose)
    project_uploader = ProjectUploader(requester, verbose)
    project_attribute_uploader = ProjectAttributeUploader(requester, verbose)
    consumption_metadata_uploader = ConsumptionMetadataUploader(requester, verbose)

    # project attribute keys
    project_attribute_keys_data = _get_project_attribute_keys_data(project_df)
    for data in project_attribute_keys_data:
        response_data = project_attribute_key_uploader.sync(data)
        import pdb;pdb.set_trace()

    for project_data, project_attributes_data in \
            _get_project_data(project_df, project_attribute_keys_data):
        # TODO actually upload projects
        # TODO replace attribute key name with id obtained from sync above ^^
        pass

    for consumption_metadata_data, consumption_records_data in \
            _get_consumption_data(consumption_df):

        # TODO actually upload consumption metadata, potentially replacing with
        #   ids obtained above.
        # TODO update datastore to take bulk consumption records
        pass

def _convert_to_dataframes(project_csv, consumption_csv):
    project_df = pd.read_csv(project_csv)
    consumption_df = pd.read_csv(consumption_csv)
    consumption_df.start = pd.to_datetime(consumption_df.start)
    consumption_df.end = pd.to_datetime(consumption_df.end)
    return project_df, consumption_df

def _get_project_attribute_keys_data(project_df):

    project_attribute_keys_data = []
    for column_name in project_df.columns:

        if column_name in constants.STANDARD_PROJECT_DATA_COLUMN_NAMES:
            continue

        if column_name in constants.STANDARD_PROJECT_ATTRIBUTE_KEYS:
            project_attribute_key = constants.STANDARD_PROJECT_ATTRIBUTE_KEYS[column_name]
            project_attribute_key_data = {
                "name": project_attribute_key["name"],
                "display_name": project_attribute_key["display_name"],
                "data_type": project_attribute_key["data_type"],
            }
        else:
            project_attribute_key_data = _infer_project_attribute_key_data(
                    column_name, project_df[column_name])

        project_attribute_keys_data.append(project_attribute_key_data)

    return project_attribute_keys_data

def _infer_project_attribute_key_data(column_name, column):
    project_attribute_key_data = {
        "name": column_name,
        "display_name": _infer_display_name(column_name),
        "data_type": _infer_data_type(column),
    }
    return project_attribute_key_data

def _infer_data_type(column):
    if column.shape[0] == 0:
        return None

    if column.dtype == "float64":
        return "FLOAT"
    elif column.dtype == "int64":
        return "INTEGER"
    elif column.dtype == "bool":
        return "BOOLEAN"
    elif column.dtype == "object":
        try:
            pd.to_datetime(column[:10])
        except ValueError:
            return "CHAR"
        try:
            datetime.strptime(column[0], "%Y-%m-%d")
            return "DATE"
        except ValueError:
            return "DATETIME"
    else:
        return None

def _infer_display_name(column_name):
    # first standardize to underscored_column_name
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', column_name)
    underscored = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

    # then convert to Not Underscored Column Name
    display_name = " ".join([ str.capitalize(w) for w in underscored.split("_")])
    return display_name

def _get_project_data(project_df, project_attribute_keys_data):
    for i, row in project_df.iterrows():
        project_data = {
            "project_id": row.project_id,
            "zipcode": row.zipcode,
            "weather_station": row.weather_station,
            "latitude": row.latitude,
            "longitude": row.longitude,
            "baseline_period_start": None,
            "baseline_period_end": row.baseline_period_end,
            "reporting_period_start": row.reporting_period_start,
            "reporting_period_end": None,
        }

        project_attributes_data = []
        for project_attribute_key_data in project_attribute_keys_data:
            data_type = project_attribute_key_data["data_type"]
            name = project_attribute_key_data["name"]
            project_attribute_data = _get_project_attribute_data(row, name, data_type)
            project_attributes_data.append(project_attribute_data)

        yield project_data, project_attributes_data

def _get_project_attribute_data(row, name, data_type):

    project_attribute_data = {
        "name": name,
    }

    if data_type == "BOOLEAN":
        project_attribute_data["boolean_value"] = (row[name] == "True")
    elif data_type == "CHAR":
        project_attribute_data["char_value"] = row[name]
    elif data_type == "DATE":
        project_attribute_data["date_value"] = row[name]
    elif data_type == "DATETIME":
        # check format, but keep as string
        dt = datetime.strptime(row[name], "%Y-%m-%dT%H:%M:%S%z")
        project_attribute_data["datetime_value"] = row["name"]
    elif data_type == "FLOAT":
        project_attribute_data["float_value"] = float(row[name])
    elif data_type == "INTEGER":
        project_attribute_data["integer_value"] = int(row[name])
    else:
        raise NotImplementedError

    return project_attribute_data

def _get_consumption_data(consumption_df):
    for project_id, project_consumption in consumption_df.groupby("project_id"):
        for fuel_type, fuel_type_consumption in project_consumption.groupby("fuel_type"):
            unique_unit_names = fuel_type_consumption.unit_name.unique()
            assert unique_unit_names.shape[0] == 1

            consumption_metadata_data = {
                "project_id": project_id,
                "fuel_type": fuel_type,
                "unit_name": unique_unit_names[0],
            }
            consumption_records_data = _get_consumption_records_data(
                    fuel_type_consumption)

            yield consumption_metadata_data, consumption_records_data

def _get_consumption_records_data(consumption_df):
    raw_consumption_records_data = _get_raw_consumption_records_data(
            consumption_df)
    consumption_records_data = _process_raw_consumption_records_data(
            raw_consumption_records_data)
    return consumption_records_data

def _get_raw_consumption_records_data(consumption_df):
    raw_consumption_records_data = []
    for i, row in consumption_df.iterrows():
        consumption_record_data = {
            "start": row.start,
            "end": row.end,
            "value": row.value,
            "estimated": row.estimated,
        }
        raw_consumption_records_data.append(consumption_record_data)
    return raw_consumption_records_data

def _process_raw_consumption_records_data(records):

    # dumb hack - the fuel_type and unit_name are actually just placeholders
    # and don't actually affect the processing. This an indication that (TODO),
    # this logic should be factored out of the ConsumptionData object.
    fuel_type, unit_name = "electricity", "kWh"
    consumption_data = ConsumptionData(records, fuel_type, unit_name,
                                       record_type="arbitrary")

    consumption_records_data = []
    for (d1, value), (d2, estimated) in zip(consumption_data.data.iteritems(), consumption_data.estimated.iteritems()):
        assert d1 == d2
        record = {
            "date": pytz.UTC.localize(d1.to_datetime()).strftime("%Y-%m-%dT%H:%M:%S%z"),
            "value": value,
            "estimated": estimated,
        }
        consumption_records_data.append(record)
    return consumption_records_data

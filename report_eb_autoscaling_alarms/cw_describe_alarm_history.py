# Writes a CSV with alarm history.
# You could use Excel afterwards on the CSV to sort by two radices: 1. NumActionFailure, 2. NumActionSuccess.
#
# for each alarm
#   get all alarm history items
#   calculate time spent in each alarm state (Days Hr Min Sec, and Percent)
#   count number of alarm action outcomes (success or failure)
#   get mapped asg autoscaling activities
#   count number of autoscaling launching/terminating activities mapped to this alarm
#
# CSV row format:
# alarmName OK-abstime OK-pcttime INSUFFICIENT_DATA-abstime INSUF-pcttime ALARM-abstime ALARM-pcttime #Action-Success #Action-Failure
#

import boto3.session
from pprint import pformat
from pathlib import Path
from datetime import datetime, timedelta
import pytz
import dateutil.parser
import json
from report_eb_autoscaling_alarms import cw_describe_alarms, aws_cache, util

MAX_PAGES = 10000
_cw_client = None


def init_client(profile_name, region_name):
    cw_session = boto3.session.Session(profile_name=profile_name, region_name=region_name)
    global _cw_client
    _cw_client = cw_session.client('cloudwatch')
    

# Returns list of describe_alarm_history paginated responses.
def get_history_pages(alarm_name, refresh_cache=False):
    key = 'describe_alarm_history-' + alarm_name
    if aws_cache.has_key(key) and not refresh_cache:
        return aws_cache.cache_get(key)
    done = False
    next_token = None
    history_pages = []
    while not done and len(history_pages) < MAX_PAGES:
        if next_token:
            history_page = _cw_client.describe_alarm_history(AlarmName=alarm_name, NextToken=next_token)
        else:
            history_page = _cw_client.describe_alarm_history(AlarmName=alarm_name)
        history_pages.append(history_page)
        if 'NextToken' in history_page and history_page['NextToken']:
            next_token = history_page['NextToken']
        else:
            done = True
    if len(history_pages) == MAX_PAGES:
        print('WARNING: {} results truncated at {} pages'.format(key, MAX_PAGES))
    aws_cache.cache_put(key, history_pages)
    return history_pages


def calc_and_write_alarm_history_for_eb_autoscaling(refresh_cache = False):
    # refresh_cache applies here to history pages, but not envs, resources, or alarms (those are
    # refreshed at module start).
    alarms = cw_describe_alarms.get_filtered_alarms([
        {'AlarmDescription': 'ElasticBeanstalk Default Scale Down alarm'},
        {'AlarmDescription': 'ElasticBeanstalk Default Scale Up alarm'}
    ])
    summary_rows = []
    for alarm in alarms:
        history_pages = get_history_pages(alarm['AlarmName'], refresh_cache)
        summary_rows.append(summarize_alarm_and_history(alarm, history_pages))
    write_alarm_history(summary_rows)


def write_alarm_history(summary_rows):
    util.ensure_path_exists(util.OUTPUT_DIR)
    output_filename = Path(util.OUTPUT_DIR + '/cw_alarm_history.csv')
    with output_filename.open(mode='w', encoding='UTF-8') as output_file:
        write_column_headers(output_file)
        for summary_row in summary_rows:
            write_summary_row(summary_row, output_file)
    print('wrote {} alarms into {}'.format(len(summary_rows), output_filename))


def write_column_headers(output_file):
    columns = [
        'AlarmName',
        'AlarmDescription',
        'Namespace',
        'DimensionName',
        'DimensionValue',
        'EnvName',
        'ThresholdCondition',
        'OKAbsTime',
        'OKPctTime',
        'ALARMAbsTime',
        'ALARMPctTime',
        'INSUFAbsTime',
        'INSUFPctTime',
        'NumActionSuccess',
        'NumActionFailure'
    ]
    output_file.write(','.join(columns) + '\n')


def write_summary_row(row, output_file):
    columns = [
        row['AlarmName'],
        row['AlarmDescription'],
        row['Namespace'],
        row['DimensionName'],
        row['DimensionValue'],
        row['EnvName'],
        row['ThresholdCondition'],
        util.quote(row['OKAbsTime']),
        row['OKPctTime'],
        util.quote(row['ALARMAbsTime']),
        row['ALARMPctTime'],
        util.quote(row['INSUFAbsTime']),
        row['INSUFPctTime'],
        str(row['NumActionSuccess']),
        str(row['NumActionFailure'])
    ]
    output_file.write(','.join(columns) + '\n')


# Returns a summary of the alarm and its history.
def summarize_alarm_and_history(alarm, history_pages):
    # Cached envs & resources are refreshed at module start, not here.
    dimension_name, dimension_value, env_name = cw_describe_alarms.get_alarm_dimension(alarm)

    action_items, state_update_items, config_update_items = filter_items(history_pages)

    error_context = 'alarm {} (beanstalk env {})'.format(alarm['AlarmName'], env_name)

    ok_abs_time, ok_pct_time, alarm_abs_time, alarm_pct_time, insuf_abs_time, insuf_pct_time\
        = calc_state_times(alarm, state_update_items, error_context)

    num_action_success, num_action_failure = calc_action_outcomes(action_items, error_context)

    return {
        'AlarmName': alarm['AlarmName'],
        'AlarmDescription': alarm['AlarmDescription'],
        'Namespace': alarm['Namespace'],
        'DimensionName': dimension_name,
        'DimensionValue': dimension_value,
        'EnvName': env_name,
        'ThresholdCondition': cw_describe_alarms.threshold_condition_to_string(alarm),
        'OKAbsTime': ok_abs_time,
        'OKPctTime': ok_pct_time,
        'ALARMAbsTime': alarm_abs_time,
        'ALARMPctTime': alarm_pct_time,
        'INSUFAbsTime': insuf_abs_time,
        'INSUFPctTime': insuf_pct_time,
        'NumActionSuccess': num_action_success,
        'NumActionFailure': num_action_failure
    }


def filter_items(history_pages):
    action_items = []
    state_update_items = []
    config_update_items = []
    for history_page in history_pages:
        for item in history_page['AlarmHistoryItems']:
            item_type = item['HistoryItemType']
            if item_type == 'Action':
                action_items.append(item)
            elif item_type == 'StateUpdate':
                state_update_items.append(item)
            elif item_type == 'ConfigurationUpdate':
                config_update_items.append(item)
            else:
                print('WARNING: AlarmHistoryItem with unknown type {}: {}'.format(item_type, pformat(item)))
    return action_items, state_update_items, config_update_items


# Each item has HistoryData with oldState, newState, so you can subtract their timestamps to derive how much time was
# spent in the oldState.  We also consider "now" minus the latest newState timestamp.
#
# In the event of no history items, the latest state and start date are on the alarm.
#
# Anecdotally it appears that the newState of one item is always the oldState of another, but I'm not sure I can rely
# on that.  So I decided against the idea of sorting the items by date to try and line up newState to newState in
# chronologically consecutive items.
#
def calc_state_times(alarm, state_update_items, error_context):
    timedelta_in_state = {'OK': timedelta(0), 'ALARM': timedelta(0), 'INSUFFICIENT_DATA': timedelta(0)}
    latest_new_start_date = pytz.utc.localize(datetime(1900, 1, 1))
    latest_state = None
    latest_datasource = None
    error_context = '{}: StateUpdate history item'.format(error_context)
    if len(state_update_items) > 0:
        for item in state_update_items:
            history_data = json.loads(item['HistoryData'])
            old_state, old_start_date = extract_state(history_data, 'oldState', error_context)
            new_state, new_start_date = extract_state(history_data, 'newState', error_context)
            if old_start_date and new_start_date:
                timedelta_in_state[old_state] += new_start_date - old_start_date
            if new_start_date and new_start_date > latest_new_start_date:
                latest_new_start_date = new_start_date
                latest_state = history_data['newState']['stateValue']
                latest_datasource = 'latest StateUpdate history item (newState)'
    else:
        latest_new_start_date = alarm['StateUpdatedTimestamp']
        latest_state = alarm['StateValue']
        latest_datasource = 'alarm state'
        validate_state(latest_state, 'alarm', alarm, error_context)

    now = datetime.now(latest_new_start_date.tzinfo)
    if now < latest_new_start_date:
        print('WARNING: {}: {} timestamp {} is more recent than "now" {})'
              .format(error_context, latest_datasource, latest_new_start_date, now))
    else:
        timedelta_in_state[latest_state] += now - latest_new_start_date

    ok_abs_time = str(timedelta_in_state['OK'])
    alarm_abs_time = str(timedelta_in_state['ALARM'])
    insuf_abs_time = str(timedelta_in_state['INSUFFICIENT_DATA'])
    total_timedelta = timedelta_in_state['OK'] + timedelta_in_state['ALARM'] + timedelta_in_state['INSUFFICIENT_DATA']
    ok_pct_time = '{0:.2f}%'.format(100.0 * (timedelta_in_state['OK'] / total_timedelta))
    alarm_pct_time = '{0:.2f}%'.format(100.0 * (timedelta_in_state['ALARM'] / total_timedelta))
    insuf_pct_time = '{0:.2f}%'.format(100.0 * (timedelta_in_state['INSUFFICIENT_DATA'] / total_timedelta))

    # Example output
    # '1 day, 0:46:30', '85.84%', '4:05:10', '14.16%', '0:00:00', '0.00%'
    return ok_abs_time, ok_pct_time, alarm_abs_time, alarm_pct_time, insuf_abs_time, insuf_pct_time


def extract_state(history_data, state_key, error_context):
    if state_key not in history_data:
        raise ValueError('{}: missing state key {}: {}'.format(error_context, state_key, history_data))
    if 'stateValue' not in history_data[state_key]:
        raise ValueError('{}: {} missing state value: {}'.format(error_context, state_key, history_data))
    state_value = history_data[state_key]['stateValue']
    validate_state(state_value, state_key, history_data, error_context)
    if 'stateReasonData' in history_data[state_key] and 'startDate' in history_data[state_key]['stateReasonData']:
        start_date = dateutil.parser.parse(history_data[state_key]['stateReasonData']['startDate'])
    else:
        start_date = None
        print('WARNING: {}: {} startDate unavailable: {}'.format(error_context, state_key, history_data))
    return state_value, start_date


def validate_state(state_value, container_name, container, error_context):
    if state_value != 'ALARM' and state_value != 'OK' and state_value != 'INSUFFICIENT_DATA':
        raise ValueError('{}: {} with unknown state value {}: {}'.format(error_context, container_name, state_value, container))


# Count the number of actions ending in success or failure.
def calc_action_outcomes(action_items, error_context):
    num_action_success, num_action_failure = 0, 0
    for item in action_items:
        history_data = json.loads(item['HistoryData'])
        action_state = history_data['actionState']
        if action_state == 'Succeeded':
            num_action_success += 1
        elif action_state == 'Failed':
            num_action_failure += 1
        else:
            print('WARNING: {}: ignoring Action history item with unknown state {} in alarm {} (beanstalk env {})'
                .format(error_context, action_state))
    return num_action_success, num_action_failure

# Writes an output CSV with summary of ASG Activity.
# You could use Excel afterwards on the CSV to sort descending NumActivityStatusSuccessful.
# Compare to the cloudwatch alarm history.

import boto3.session
from pathlib import Path
from datetime import datetime, timedelta
import pytz
import re
import json
import operator
from report_eb_autoscaling_alarms import eb_by_resource, aws_cache, util

MAX_PAGES = 10000
_asg_client = None


def init_client(profile_name, region_name):
    asg_session = boto3.session.Session(profile_name=profile_name, region_name=region_name)
    global _asg_client
    _asg_client = asg_session.client('autoscaling')


# Returns list of describe_scaling_activities paginated responses.
def get_scaling_activity_pages(asg_name, refresh_cache=False):
    key = 'describe_scaling_activities-' + asg_name
    if aws_cache.has_key(key) and not refresh_cache:
        return aws_cache.cache_get(key)
    done = False
    next_token = None
    activity_pages = []
    while not done and len(activity_pages) < MAX_PAGES:
        if next_token:
            history_page = _asg_client.describe_scaling_activities(AutoScalingGroupName=asg_name, NextToken=next_token)
        else:
            history_page = _asg_client.describe_scaling_activities(AutoScalingGroupName=asg_name)
        activity_pages.append(history_page)
        if 'NextToken' in history_page and history_page['NextToken']:
            next_token = history_page['NextToken']
        else:
            done = True
    if len(activity_pages) == MAX_PAGES:
        print('WARNING: {} results truncated at {} pages'.format(key, MAX_PAGES))
    aws_cache.cache_put(key, activity_pages)
    return activity_pages


# Returns list of describe_auto_scaling_groups paginated responses.
def get_asg(asg_name, refresh_cache=False):
    key = 'describe_auto_scaling_groups-' + asg_name
    if aws_cache.has_key(key) and not refresh_cache:
        return aws_cache.cache_get(key)
    asg = _asg_client.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name])
    aws_cache.cache_put(key, asg)
    return asg


def calc_and_write_scaling_activity_for_beanstalk_asgs(refresh_cache=False):
    # refresh_cache applies here to asg and scaling_activity, but not envs, resources, or alarms (those are
    # refreshed at module start).
    asg_env_pairs = lookup_beanstalk_asg_env_pairs(refresh_cache)
    summary_rows = []
    for asg_env_pair in asg_env_pairs:
        asg, env_name = asg_env_pair['ASG']['AutoScalingGroups'][0], asg_env_pair['EnvName']
        activity_pages = get_scaling_activity_pages(asg['AutoScalingGroupName'], refresh_cache)
        summary_rows.append( calc_scaling_activity_one_asg(activity_pages, asg, env_name) )
    write_scaling_activity_for_beanstalk_asgs(summary_rows)


def write_scaling_activity_for_beanstalk_asgs(summary_rows):
    util.ensure_path_exists(util.OUTPUT_DIR)
    output_filename = Path(util.OUTPUT_DIR + '/asg_activities.csv')
    with output_filename.open(mode='w', encoding='UTF-8') as output_file:
        write_column_headers(output_file)
        num_written = 0
        for summary_row in summary_rows:
            write_summary_row(summary_row, output_file)
            num_written += 1
    print('wrote scaling activity for {} ASGs into {}'.format(num_written, output_filename))


def write_column_headers(output_file):
    columns = [
        'ASGName',
        'EnvName',
        'ASGMin',
        'ASGMax',
        'ActivityMaxAge',
        'NumActivity',
        'NumActivityStatusSuccessful',
        'NumActivityStatusFailed',
        'NumActivityDescLaunching',
        'NumActivityDescTerminating',
        'NumAlarmsCauseLaunching',
        'NumAlarmsCauseTerminating',
        'NameAlarmsCauseLaunching',
        'NameAlarmsCauseTerminating'
    ]
    output_file.write(','.join(columns) + '\n')


def write_summary_row(row, output_file):
    columns = [
        row['ASGName'],
        row['EnvName'],
        str(row['ASGMin']),
        str(row['ASGMax']),
        util.quote(row['ActivityMaxAge']),
        str(row['NumActivity']),
        str(row['NumActivityStatusSuccessful']),
        str(row['NumActivityStatusFailed']),
        str(row['NumActivityDescLaunching']),
        str(row['NumActivityDescTerminating']),
        str(row['NumAlarmsCauseLaunching']),
        str(row['NumAlarmsCauseTerminating']),
        util.quote(row['NameAlarmsCauseLaunching']),
        util.quote(row['NameAlarmsCauseTerminating'])
    ]
    output_file.write(','.join(columns) + '\n')


def lookup_beanstalk_asg_env_pairs(refresh_cache):
    asg_env_pairs = []
    envs = eb_by_resource.get_envs()
    for env in envs['Environments']:
        env_name = env['EnvironmentName']
        resources = eb_by_resource.get_resources(env_name)
        for asg_resource in resources['EnvironmentResources']['AutoScalingGroups']:
            asg_name = asg_resource['Name']
            asg = get_asg(asg_name, refresh_cache)
            asg_env_pairs.append({
                'ASG': asg,
                'EnvName': env_name
            })
    return asg_env_pairs


# Returns a summary of the asg and its scaling activity.
def calc_scaling_activity_one_asg(activity_pages, asg, env_name):
    far_in_the_future = pytz.utc.localize(datetime(2999, 12, 31))
    oldest_start_time = far_in_the_future
    total_activity_count = 0
    activity_counts = {'Successful': 0, 'Failed': 0, 'Launching': 0, 'Terminating': 0}
    alarm_causes = {'Launching': {}, 'Terminating': {}}
    for activity_page in activity_pages:
        for scaling_activity in activity_page['Activities']:

            # http://docs.aws.amazon.com/AutoScaling/latest/APIReference/API_Activity.html

            total_activity_count += 1

            start_time = util.ensure_tz(scaling_activity['StartTime'])
            if start_time < oldest_start_time:
                oldest_start_time = start_time

            status_code = scaling_activity['StatusCode']
            if status_code == 'Successful' or status_code == 'Failed':
                increment_activity_count(activity_counts, status_code)

            alarm_name = extract_alarm_name(scaling_activity)

            m = re.match('^(Launching|Terminating)', scaling_activity['Description'])
            if m:
                launch_or_term = m.group(1)
                increment_activity_count(activity_counts, launch_or_term)
                increment_alarm_causes(alarm_causes, launch_or_term, alarm_name)

    if oldest_start_time == far_in_the_future:
        activity_max_age = timedelta(0)
    else:
        now = datetime.now(oldest_start_time.tzinfo)
        activity_max_age = now - oldest_start_time

    num_alarms_launching, name_alarms_launching = summarize_alarm_causes(alarm_causes, 'Launching')
    num_alarms_terminating, name_alarms_terminating = summarize_alarm_causes(alarm_causes, 'Terminating')

    return {
        'ASGName': asg['AutoScalingGroupName'],
        'EnvName': env_name,
        'ASGMin': asg['MinSize'],
        'ASGMax': asg['MaxSize'],
        'ActivityMaxAge': activity_max_age,
        'NumActivity': total_activity_count,
        'NumActivityStatusSuccessful': activity_counts['Successful'],
        'NumActivityStatusFailed': activity_counts['Failed'],
        'NumActivityDescLaunching': activity_counts['Launching'],
        'NumActivityDescTerminating': activity_counts['Terminating'],
        'NumAlarmsCauseLaunching': num_alarms_launching,
        'NumAlarmsCauseTerminating': num_alarms_terminating,
        'NameAlarmsCauseLaunching': name_alarms_launching,
        'NameAlarmsCauseTerminating': name_alarms_terminating
    }


def extract_alarm_name(scaling_activity):
    # Two ways to get alarm name: 1. activity Details (structured json), 2. activity Cause (parse freeform string).
    # Choosing Details.
    if 'Details' in scaling_activity:
        details = json.loads(scaling_activity['Details'])
        if 'InvokingAlarms' in details and len(details['InvokingAlarms']) > 0:
            return details['InvokingAlarms'][0]['AlarmName']
    return 'Unknown_Alarm'


def increment_activity_count(activity_counts, key):
    if key in activity_counts:
        activity_counts[key] += 1
    else:
        activity_counts[key] = 1


def increment_alarm_causes(alarm_causes, launch_or_term, alarm_name):
    if alarm_name in alarm_causes[launch_or_term]:
        alarm_causes[launch_or_term][alarm_name] += 1
    else:
        alarm_causes[launch_or_term][alarm_name] = 1


def summarize_alarm_causes(alarm_causes, launch_or_term):
    items = alarm_causes[launch_or_term].items()
    counted_names = []
    for alarm_name, count in sorted(items, key=operator.itemgetter(1), reverse=True):
        counted_names.append('{} {}'.format(alarm_name, count))
    return len(items), ', '.join(counted_names)
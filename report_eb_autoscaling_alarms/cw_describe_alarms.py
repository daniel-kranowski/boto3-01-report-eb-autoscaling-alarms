# The alarms involve ASGs with long squiggly names ... here we map the ASG names to meaningful beanstalk env names.
# You could use Excel afterwards on the CSV to sort the output by StateUpdatedTimestamp, or Filter by other columns.

import boto3.session
from pprint import pformat
from pathlib import Path
from report_eb_autoscaling_alarms import eb_by_resource, aws_cache, util

MAX_PAGES = 10000
_cw_client = None


def init_client(profile_name, region_name):
    cw_session = boto3.session.Session(profile_name=profile_name, region_name=region_name)
    global _cw_client
    _cw_client = cw_session.client('cloudwatch')
    

# Returns list of describe_alarms paginated responses.
def get_alarm_pages(refresh_cache=False):
    key = 'describe_alarms'
    if aws_cache.has_key(key) and not refresh_cache:
        return aws_cache.cache_get(key)
    done = False
    next_token = None
    alarm_pages = []
    while not done and len(alarm_pages) < MAX_PAGES:
        if next_token:
            alarm_page = _cw_client.describe_alarms(NextToken=next_token)
        else:
            alarm_page = _cw_client.describe_alarms()
        alarm_pages.append(alarm_page)
        if 'NextToken' in alarm_page and alarm_page['NextToken']:
            next_token = alarm_page['NextToken']
        else:
            done = True
    if len(alarm_pages) == MAX_PAGES:
        print('WARNING: {} results truncated at {} pages'.format(key, MAX_PAGES))
    aws_cache.cache_put(key, alarm_pages)
    return alarm_pages


def get_filtered_alarms(criteria, refresh_cache=False):
    if not isinstance(criteria, list):
        raise ValueError('criteria argument must be list, not {}'.format(type(criteria)))
    alarms = []
    alarm_pages = get_alarm_pages(refresh_cache)
    for alarm_page in alarm_pages:
        for alarm in alarm_page['MetricAlarms']:
            if match_alarm(alarm, criteria):
                alarms.append(alarm)
    return alarms


# Example input criteria:
# [ { "AlarmDescription": "ElasticBeanstalk Default Scale Down alarm" },
#   { "AlarmDescription": "ElasticBeanstalk Default Scale Up alarm" } ]
#
# Returns true if any criterion matches the alarm.
#
def match_alarm(alarm, criteria):
    for criterion in criteria:
        for k, v in criterion.items():
            if k in alarm and alarm[k] == v:
                return True
    return False


def get_alarm_dimension(alarm):
    dimension_name = ''
    dimension_value = ''
    env_name = ''
    if len(alarm['Dimensions']) > 0:
        dimension_name = alarm['Dimensions'][0]['Name']
        dimension_value = alarm['Dimensions'][0]['Value']
        if dimension_name == 'AutoScalingGroupName':
            env_name = eb_by_resource.find_env_with_resource({'AutoScalingGroups': {'Name': dimension_value}})
    return dimension_name, dimension_value, env_name


def threshold_condition_to_string(alarm):
    return '{} {} {}'.format(alarm['MetricName'], comparison_operator_to_string(alarm), alarm['Threshold'])


# http://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-cw-alarm.html
def comparison_operator_to_string(alarm):
    op = alarm['ComparisonOperator']
    if op == 'GreaterThanOrEqualToThreshold':
        return '>='
    elif op == 'GreaterThanThreshold':
        return '>'
    elif op == 'LessThanThreshold':
        return '<'
    elif op == 'LessThanOrEqualToThreshold':
        return '<='


def write_alarms():
    # No need for a refresh_cache arg, we only depend on 'alarms' and those were refreshed already if user wanted it.
    util.ensure_path_exists(util.OUTPUT_DIR)
    output_filename = Path(util.OUTPUT_DIR + '/cw_alarms.csv')
    with output_filename.open(mode='w', encoding='UTF-8') as output_file:
        write_column_headers(output_file)
        num_written = 0
        alarm_pages = get_alarm_pages()
        for alarm_page in alarm_pages:
            for alarm in alarm_page['MetricAlarms']:
                if len(alarm['Dimensions']) <= 1:
                    write_alarm(alarm, output_file)
                    num_written += 1
                else:
                    print('WARNING: cannot handle multi-dimensional alarm: {}', pformat(alarm))
    print('wrote {} alarms into {}'.format(num_written, output_filename))


def write_column_headers(output_file):
    columns = [
        'AlarmName',
        'AlarmDescription',
        'StateUpdatedTimestamp',
        'StateValue',
        'Namespace',
        'DimensionName',
        'DimensionValue',
        'EnvName',
        'MetricName',
        'StateReason'
    ]
    output_file.write(','.join(columns) + '\n')


def write_alarm(alarm, output_file):
    (dimension_name, dimension_value, env_name) = get_alarm_dimension(alarm)
    columns = [
        alarm['AlarmName'],
        alarm.get('AlarmDescription', ''), # Could be missing
        str(alarm['StateUpdatedTimestamp']),
        alarm['StateValue'],
        alarm['Namespace'],
        dimension_name,
        dimension_value,
        env_name,
        alarm['MetricName'],
        util.quote(alarm['StateReason'])
    ]
    output_file.write(','.join(columns) + '\n')



import argparse
from report_eb_autoscaling_alarms import cw_describe_alarm_history, cw_describe_alarms, asg_describe_scaling, \
    eb_by_resource, eb_refresh_cache


# Parses command-line arguments and returns them as 'options'.
def parse():
    parser = argparse.ArgumentParser(
        prog='report_eb_autoscaling_alarms',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="""
        Retrieves Cloudwatch alarm history and ASG scaling activities for an Elastic Beanstalk environment.
        """
    )
    parser.add_argument('--recache', help='Force a cache refresh on one or more object types.  To refresh all, ' +
                        'simply delete the cache dir before running.',
                        choices=['envs', 'resources', 'alarms', 'alarm_history', 'scaling'], nargs='+', default=[])
    parser.add_argument('--write-csv', help='Write one or more output CSV files.',
                        choices=['cw_alarms', 'cw_alarm_history', 'asg_activities', 'all'], nargs='+', default=[])
    parser.add_argument('--aws-profile', help='Profile name in your AWS credentials file.', default='default')
    parser.add_argument('--aws-region', help='AWS Region to query.', default='us-west-2')
    options = parser.parse_args()
    if 'all' in options.write_csv:
        options.write_csv = ['cw_alarms', 'cw_alarm_history', 'asg_activities']
    elif options.recache is None and options.write_csv is None:
        raise Exception('Please specify at least one recache or csv target')
    return options


# Initializes the Boto AWS clients.
#
# aws_profile: string name, like 'default'
# aws_region: string name, like 'us-west-2'
#
def init_clients(aws_profile, aws_region):
    asg_describe_scaling.init_client(aws_profile, aws_region)
    cw_describe_alarm_history.init_client(aws_profile, aws_region)
    cw_describe_alarms.init_client(aws_profile, aws_region)
    eb_by_resource.init_client(aws_profile, aws_region)
    eb_refresh_cache.init_client(aws_profile, aws_region)


# Refreshes the cache (or fills it for the first time), for the "easy" cache object types: envs, resources, alarms.
# With alarm_history and scaling, it is easier to defer the refresh til later when the write_csv function knows what
# arguments to pass to boto.
#
# recache: list of string: object types
#
def refresh_cache(recache):
    # Recache describe_environments
    envs = []
    if 'envs' in recache or 'resources' in recache:
        envs = eb_by_resource.get_envs(True)

    # Recache describe_environment_resources-<envname>
    if 'resources' in recache:
        for env in envs['Environments']:
            eb_by_resource.get_resources(env['EnvironmentName'], True)

    # Recache describe_alarms
    if 'alarms' in recache:
        cw_describe_alarms.get_alarm_pages(True)


# Writes CSV files for the specified object types.
#
# write_csv: list of string: object types
#
def write_csvs(write_csv, recache):
    # Write output/cw_alarms.csv
    if 'cw_alarms' in write_csv:
        cw_describe_alarms.write_alarms()

    # Write output/cw_alarm_history.csv
    if 'cw_alarm_history' in write_csv:
        cw_describe_alarm_history.calc_and_write_alarm_history_for_eb_autoscaling('alarm_history' in recache)

    # Write output/asg_activities.csv
    if 'asg_activities' in write_csv:
        asg_describe_scaling.calc_and_write_scaling_activity_for_beanstalk_asgs('scaling' in recache)


if __name__ == '__main__':
    options = parse()
    init_clients(options.aws_profile, options.aws_region)
    refresh_cache(options.recache)
    write_csvs(options.write_csv, options.recache)

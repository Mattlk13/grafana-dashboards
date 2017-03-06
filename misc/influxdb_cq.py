#!/usr/bin/env python

"""Script for generating continuous queries for InfluxDB"""

import optparse
import yaml

import influxdb

PROMETHEUS_DB = 'prometheus'
TRENDING_DB = 'trending'
INTERVALS = ['5m', '1h']

METRICS = yaml.load("""
mysql_global_status_bytes_received: {type: counter}
mysql_global_status_bytes_sent: {type: counter}
mysql_global_status_connections: {type: counter}
mysql_global_status_queries: {type: counter}
node_cpu: {type: counter, group_by: 'mode, cpu'}
node_disk_bytes_read: {type: counter, group_by: device}
node_disk_bytes_written: {type: counter, group_by: device}
node_disk_reads_completed: {type: counter, group_by: device}
node_disk_writes_completed: {type: counter, group_by: device}
node_filesystem_avail: {type: gauge, group_by: 'mountpoint, fstype, device'}
node_filesystem_size: {type: gauge, group_by: 'mountpoint, fstype, device'}
node_load1: {type: gauge}
node_memory_Buffers: {type: gauge}
node_memory_Cached: {type: gauge}
node_memory_MemAvailable: {type: gauge}
node_memory_MemFree: {type: gauge}
node_memory_MemTotal: {type: gauge}
node_network_receive_bytes: {type: counter, group_by: device}
node_network_transmit_bytes: {type: counter, group_by: device}
""")


def main():
    """Main func"""
    parser = optparse.OptionParser()
    parser.add_option('--exit-on-cq', action='store_true', default=False, help='Exit when continuous queries exist')
    parser.add_option('--drop-db', action='store_true', default=False, help='Drop trending db')
    options, _ = parser.parse_args()

    client = influxdb.InfluxDBClient('localhost', 8086, 'root', 'root', PROMETHEUS_DB)

    # Drop all existing CQ from prometheus db
    queries = []
    result = client.query('SHOW CONTINUOUS QUERIES;')
    for i in result.raw['series']:
        if i['name'] == PROMETHEUS_DB and 'values' in i:
            queries = [i[0] for i in i['values']]

    # Exit when --check-cq is set and CQ already exist
    if options.exit_on_cq and queries:
        print '[{0!s}] {1!s} continuous queries exist.'.format(PROMETHEUS_DB, len(queries))
        return

    count = 0
    for name in queries:
        client.query('DROP CONTINUOUS QUERY {0!s} ON {1!s};'.format(name, PROMETHEUS_DB))
        count += 1

    print '[{0!s}] Deleted {1!s} continuous queries.'.format(PROMETHEUS_DB, count)

    # Recreate trending db
    if options.drop_db:
        client.drop_database(TRENDING_DB)
        print '[{0!s}] Database dropped.'.format(TRENDING_DB)

    dbs = [x['name'] for x in client.get_list_database()]
    if TRENDING_DB not in dbs:
        client.create_database(TRENDING_DB, if_not_exists=True)
        print '[{0!s}] Database created.'.format(TRENDING_DB)

    # Create new CQ
    count = 0
    retentions = [x['name'] for x in client.get_list_retention_policies(database=TRENDING_DB)]
    for interval in INTERVALS:
        # Create retention
        if interval not in retentions:
            client.create_retention_policy('"{0!s}"'.format(interval), 'INF', '1', TRENDING_DB)
            print '[{0!s}] Retention policy "{1!s}" created.'.format(TRENDING_DB, interval)

        for metric, data in METRICS.iteritems():
            params = {'metric': metric,
                      'interval': interval,
                      'prom_db': PROMETHEUS_DB,
                      'trend_db': TRENDING_DB,
                      'select': '',
                      'group': ''}
            if data['type'] == 'gauge':
                params['select'] = 'MEAN(value)'
            elif data['type'] == 'counter':
                params['select'] = 'MAX(value)'

            if 'group_by' in data:
                params['group'] = ', {0!s}'.format(data['group_by'])

            query = """CREATE CONTINUOUS QUERY {metric!s}_{interval!s} ON {prom_db!s}
                BEGIN
                    SELECT {select!s} INTO {trend_db!s}."{interval!s}".{metric!s}
                    FROM {metric!s} GROUP BY time({interval!s}), alias{group!s}
                END;
            """.format(**params)
            client.query(query)
            count += 1

    print '[{0!s}] Added {1!s} continuous queries.'.format(PROMETHEUS_DB, count)


if __name__ == '__main__':
    main()

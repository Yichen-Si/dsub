# Copyright 2026 Verily Life Sciences Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tests for Batch job dependencies, event-based times, and dstat run time."""

import datetime
import unittest

from dsub.commands import dsub as dsub_command
from dsub.lib import job_model
from dsub.lib import output_formatter
from dsub.providers import google_batch_operations as ops
from google.cloud import batch_v1alpha
from google.protobuf import timestamp_pb2

UTC = datetime.timezone.utc


def _ts(seconds):
  t = timestamp_pb2.Timestamp()
  t.FromSeconds(seconds)
  return t


def _job(state, transitions, update=None):
  """Build a v1alpha Job with "from A to B" status events at given times."""
  job = batch_v1alpha.Job()
  if state is not None:
    job.status.state = state
  events = []
  for when, old, new in transitions:
    events.append(
        batch_v1alpha.StatusEvent(
            description=f'Job state is set from {old} to {new} for job x',
            event_time=_ts(when)))
  job.status.status_events = events
  if update is not None:
    job.update_time = _ts(update)
  return job


class FakeTask(object):

  def __init__(self, **fields):
    self._fields = fields

  def get_field(self, field, default=None):
    value = self._fields.get(field)
    return default if value is None else value


class BatchApiSelectionTest(unittest.TestCase):

  def tearDown(self):
    ops.select_api('v1')
    super().tearDown()

  def test_select_and_build_dependency(self):
    module = ops.select_api('v1alpha')
    self.assertIs(module, batch_v1alpha)
    dep = ops.build_job_dependency(['projects/p/locations/l/jobs/a'],
                                   'succeeded')
    self.assertEqual(
        dict(dep.items),
        {'projects/p/locations/l/jobs/a': batch_v1alpha.JobDependency.Type.SUCCEEDED})
    job = ops.build_job([], batch_v1alpha.AllocationPolicy(), {},
                        batch_v1alpha.LogsPolicy(), [dep])
    self.assertEqual(len(job.dependencies), 1)

  def test_v1_rejects_dependencies(self):
    ops.select_api('v1')
    with self.assertRaises(ValueError):
      ops.build_job_dependency(['projects/p/locations/l/jobs/a'], 'succeeded')

  def test_unknown_version(self):
    with self.assertRaises(ValueError):
      ops.select_api('v2')


class BatchEventTimesTest(unittest.TestCase):

  def test_running_job(self):
    job = _job(batch_v1alpha.JobStatus.State.RUNNING,
               [(100, 'QUEUED', 'SCHEDULED'), (160, 'SCHEDULED', 'RUNNING')],
               update=170)
    self.assertIn('1970-01-01T00:02:40', ops.get_start_time(job))
    self.assertIsNone(ops.get_end_time(job))
    self.assertEqual(ops.get_state_name(job), 'RUNNING')

  def test_finished_job(self):
    job = _job(batch_v1alpha.JobStatus.State.SUCCEEDED,
               [(160, 'SCHEDULED', 'RUNNING'), (400, 'RUNNING', 'SUCCEEDED')],
               update=410)
    self.assertIn('1970-01-01T00:06:40', ops.get_end_time(job))

  def test_state_name_falls_back_to_events(self):
    job = _job(None, [(100, 'WAITING', 'QUEUED')])
    self.assertEqual(ops.get_state_name(job), 'QUEUED')
    self.assertIsNone(ops.get_start_time(job))


class RunTimeTest(unittest.TestCase):

  def test_format(self):
    self.assertEqual(output_formatter.format_run_time(59), '0:00:59')
    self.assertEqual(output_formatter.format_run_time(3725), '1:02:05')
    self.assertEqual(output_formatter.format_run_time(90061), '1d 1:01:01')

  def test_finished_running_and_waiting(self):
    start = datetime.datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
    end = start + datetime.timedelta(minutes=5, seconds=3)
    now = start + datetime.timedelta(hours=2)
    done = FakeTask(**{'start-time': start, 'end-time': end,
                       'status': 'SUCCESS'})
    self.assertEqual(output_formatter.get_run_time(done, now), '0:05:03')
    running = FakeTask(**{'start-time': start, 'status': 'RUNNING'})
    self.assertEqual(output_formatter.get_run_time(running, now), '2:00:00')
    waiting = FakeTask(status='RUNNING')
    self.assertIsNone(output_formatter.get_run_time(waiting, now))

  def test_default_row_has_run_time(self):
    start = datetime.datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
    task = FakeTask(**{'job-name': 'j', 'start-time': start,
                       'end-time': start + datetime.timedelta(seconds=61),
                       'status': 'SUCCESS', 'status-message': 'SUCCESS'})
    row = output_formatter.prepare_row(task, full=False, summary=False)
    self.assertEqual(row['run-time'], '0:01:01')
    text = output_formatter.TextOutput(False).prepare_output(row)
    self.assertEqual(text['Run Time'], '0:01:01')


class DependencyArgsTest(unittest.TestCase):

  def _parse(self, extra):
    argv = ['--provider', 'google-batch', '--project', 'p', '--logging',
            'gs://b/log', '--command', 'true'] + extra
    return dsub_command._parse_arguments('dsub', argv)

  def test_batch_after_selects_v1alpha(self):
    args = self._parse(['--batch-after', 'job-a', 'job-b'])
    self.assertEqual(args.batch_api_version, 'v1alpha')
    resources = dsub_command._get_job_resources(args)
    self.assertEqual(resources.batch_after, ['job-a', 'job-b'])
    self.assertEqual(resources.batch_after_condition, 'succeeded')

  def test_batch_after_conflicts_with_v1(self):
    with self.assertRaises(ValueError):
      self._parse(['--batch-after', 'job-a', '--batch-api-version', 'v1'])

  def test_batch_after_requires_google_batch(self):
    with self.assertRaises(ValueError):
      dsub_command._parse_arguments(
          'dsub', ['--provider', 'local', '--logging', '/tmp/log',
                   '--command', 'true', '--batch-after', 'job-a'])

  def test_metadata_round_trip(self):
    resources = job_model.Resources(batch_after=['job-a'],
                                    batch_after_condition='finished')
    self.assertEqual(resources.batch_after, ['job-a'])
    self.assertIsNone(job_model.Resources().batch_after)


if __name__ == '__main__':
  unittest.main()

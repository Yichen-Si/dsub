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

"""Unit tests for Google Batch mounts."""

import unittest

from dsub.lib import job_model
from dsub.providers import google_batch


class TestGoogleBatchMounts(unittest.TestCase):

  def _create_test_job_descriptor(self, mounts):
    job_metadata = {
        'script': job_model.Script('test.sh', 'echo hello'),
        'job-id': 'test-job-id',
        'job-name': 'test-job-name',
        'user-id': 'test-user',
        'user-project': 'test-project',
        'dsub-version': '1-0-0',
    }

    job_params = {}
    job_model.ensure_job_params_are_complete(job_params)
    job_params['mounts'] = mounts

    task_resources = job_model.Resources(
        logging_path=job_model.LoggingParam(
            'gs://test-bucket/logs.log', 'google-cloud-storage'))
    task_descriptor = job_model.TaskDescriptor(
        task_metadata={},
        task_params={
            'labels': set(),
            'envs': set(),
            'inputs': set(),
            'outputs': set(),
            'input-recursives': set(),
            'output-recursives': set(),
        },
        task_resources=task_resources)

    job_resources = job_model.Resources(image='gcr.io/test/image:latest')

    return job_model.JobDescriptor(
        job_metadata, job_params, job_resources, [task_descriptor])

  def _create_batch_request(self, job_descriptor):
    provider = google_batch.GoogleBatchJobProvider(
        dry_run=True, project='test-project', location='us-central1')
    return provider._create_batch_request(job_descriptor)

  def test_gcs_subdirectory_mount_uses_batch_remote_path(self):
    job_descriptor = self._create_test_job_descriptor(
        mounts={
            job_model.GCSMountParam(
                'MOUNT_DIR',
                'gs://test-bucket/path/to/data',
                'mount/gs/test-bucket/path/to/data/')
        })
    request = self._create_batch_request(job_descriptor)

    volumes = request.job.task_groups[0].task_spec.volumes
    self.assertEqual(volumes[1].gcs.remote_path, 'test-bucket/path/to/data')
    self.assertEqual(volumes[1].mount_path,
                     '/mnt/disks/data/mount/gs/test-bucket/path/to/data')

    user_runnable = request.job.task_groups[0].task_spec.runnables[3]
    self.assertIn(
        '/mnt/disks/data/mount/gs/test-bucket/path/to/data:'
        '/mnt/data/mount/gs/test-bucket/path/to/data',
        user_runnable.container.volumes)


if __name__ == '__main__':
  unittest.main()

# Job Control

dsub provides two simple mechanisms for specifying job dependencies. This
enables you to sequence or run in parallel multiple jobs, each of which can have
its own resource requirements, such as CPU and memory.

## Example with --wait

If your job dependencies are simple - one job needs to run after another - you
can simply use the "--wait" flag for each job that you launch.

The "--wait" flag will cause dsub to block after launching your job. It will
continue to poll until your job completes. If the job completes successfully,
then dsub will exit with status code 0, otherwise dsub exits with status code 1.

You can take advantage of the "errexit" option in bash:

```
# Enable exit on error
set -o errexit

# Launch step 1 and block until completion
dsub ... --wait

# Launch step 2 and block until completion
dsub ... --wait

# Launch step 3
dsub ...
```

If you want to handle the error explicitly, the dsub exit status can be handled as:

```
# Launch step 1 and block until completion
if ! dsub ... --wait; then
  echo "Step 1 failed!"
  exit 1
fi
```

## Example with --after

Suppose you want to run jobs A and B in parallel, and then job C.

This can be done with `--after`, passing it the job-id from A and B.

The first step is to capture the job-id for the job you want to wait for.

```
JOBID_A=$(dsub ...)
JOBID_B=$(dsub ...)
```

Then pass these values to the `--after` flag for launching Job C

```
dsub ... --after "${JOB_A}" "${JOB_B}"
```

Here is the output of a sample run:

```
$ JOBID_A=$(dsub --provider google-batch --project "${MYPROJECT}" --regions us-central1 \
--logging "gs://${MYBUCKET}/logging/"   \
--command 'echo "hello from job A"')
Job: echo--<user>--180924-112256-64
Launched job-id: echo--<user>--180924-112256-64
To check the status, run:
  dstat --provider google-batch --project ${MYPROJECT} --jobs 'echo--<user>--180924-112256-64' --status '*'
To cancel the job, run:
  ddel --provider google-batch --project ${MYPROJECT} --jobs 'echo--<user>--180924-112256-64'

$ echo "${JOBID_A}"
echo--<user>--180924-112256-64

$ JOBID_B=... (similar)

$ JOBID_C=$(dsub --provider google-batch --project "${MYPROJECT}" --regions us-central1 \
--logging "gs://${MYBUCKET}/logging/"   \
--command 'echo "job C"' --after "${JOBID_A}" "${JOBID_B}")
Waiting for predecessor jobs to complete...
Waiting for: echo--<user>--180924-112256-64, echo--<user>--180924-112259-48.
  echo--<user>--180924-112256-64: SUCCESS
Waiting for: echo--<user>--180924-112259-48.
  echo--<user>--180924-112259-48: SUCCESS
Launched job-id: echo--<user>--180924-112302-87
To check the status, run:
  dstat --provider google-batch --project ${MYPROJECT} --jobs 'echo--<user>--180924-112302-87' --status '*'
To cancel the job, run:
  ddel --provider google-batch --project ${MYPROJECT} --jobs 'echo--<user>--180924-112302-87'
echo--<user>--180924-112302-87
```

## --after is blocking

The `--after` command works by blocking dsub until the previous job(s) complete. This means
that the submission will fail if you turn off your computer before that happens.

If you'd like to be able to turn off your machine (perhaps it's a laptop and you're running
a big job) then what you can do is put your dsub command itself into a script,
and run that script using dsub itself.

## Server-side dependencies with `--batch-after` (google-batch)

With the `google-batch` provider, `--batch-after` records the dependency in the
Batch job itself instead of blocking `dsub`. Each `dsub` call returns as soon as
its job is created, so a whole pipeline can be submitted at once:

```
JOB_A=$(dsub ... --command 'echo "job A"')
JOB_B=$(dsub ... --command 'echo "job B"')
JOB_C=$(dsub ... --batch-after "${JOB_A}" "${JOB_B}" --command 'echo "job C"')
```

Batch holds job C in the `WAITING` state, using no VMs, until every task of
jobs A and B satisfies `--batch-after-condition`: `succeeded` (default),
`failed`, or `finished`. If a dependency can no longer satisfy the condition,
for example a dependency fails when `succeeded` is required, Batch fails job C
without running it. This failure cascades to anything that depends on C.

Notes:

* `--batch-after` takes `dsub` job-ids. `dsub` resolves each one to its Batch
  jobs (one per task; the latest attempt when there are several) when it
  submits. The dependencies therefore must already exist. `NO_JOB` (from
  `--skip`) is treated as already succeeded.
* Job dependencies exist only in the Batch API `v1alpha`. `--batch-after`
  selects it automatically. `--batch-api-version` or the
  `DSUB_BATCH_API_VERSION` environment variable select it explicitly; the
  default is `v1`.
* Task retries (`--retries`) happen inside a Batch job, so a preempted attempt
  does not fail its dependents unless all retries are exhausted.
* `dstat` shows waiting jobs with status `WAITING`, and their canonical status
  is `RUNNING`. `dstat --full` lists a job's `batch-after` ids under
  `provider-attributes`.

## Run time in `dstat`

The default `dstat` output includes a `Run Time` column (`[Nd ]H:MM:SS`). For a
running task it is the time since the task started; for a finished task it is
its start-to-end duration. It is blank for tasks that have not started yet,
such as queued tasks or tasks waiting on dependencies. With the `google-batch`
provider, the start is the first transition to `RUNNING` and the end is the
transition to the final state.

## Using `--skip` to bypass jobs that have already run

With the `--skip` parameter, `dsub` will skip running a job if all the outputs
for the job already exist. This useful when you are building and debugging a
sequence of jobs, such as:

```
JOBID_A=$(dsub ... --skip --output gs://${MYBUCKET}/a_file)
JOBID_B=$(dsub ... --skip --output gs://${MYBUCKET}/b_file)

dsub ... --after "${JOB_A}" "${JOB_B}"
```

If on your first run of this script, the first job, "job A" fails and the second
job, "job B" succeeds, then when you fix "job A" and re-run the script, "job B"
will be skipped. Only "job A" will be re-run. If it succeeds, then the third job
will run.

### The special `NO_JOB`  return value

When a job is skipped because the output already exists, `dsub` will output a
special job-id value, `NO_JOB`. When `NO_JOB` is passed to `--after`, `dsub`
treats that job as completed successfully.

### `--skip` caveats: wildcards and recursive output

When wildcards are used for `--output` parameters or `--output-recursive`
parameters are used, there is no way for `dsub` to verify that *all* output is
present. The best that `dsub` can do is to verify that *some* output was created
for each such parameter.

While it's allowed to specify `--output` and `--tasks` on the command line
at the same time (for example if output has wildcards and each task writes
a different file that matches the pattern), note that in this scenario
`--skip` will dutifully skip all tasks if any output matching the pattern is
present. In practice this means that it's generally unwise to use all three
of `--output`, `--tasks`, and `--skip` on the command line. Instead, specify
a different output for each task, in the tasks file.

from __future__ import absolute_import

import logging
import datetime as dt
import pickle

from google.appengine.ext import db, deferred
from google.appengine.api import taskqueue

from request_handler import RequestHandler

from models import ProblemLog, Exercise
from .models import ExerciseStatisticShard, ExerciseStatistic
import user_util

import uuid
import re

# handler that kicks off task chain per exercise
class CollectFancyExerciseStatistics(RequestHandler):
    @user_util.developer_only
    def get(self):
        # task name token
        uid = self.request_string('uid', uuid.uuid4())

        yesterday = dt.date.today() - dt.timedelta(days=1)
        yesterday_dt = dt.datetime.combine(yesterday, dt.time())
        date = self.request_date('date', "%Y/%m/%d", yesterday_dt)
        start_dt, end_dt = ExerciseStatistic.date_to_bounds(date)

        exercises = self.request_string('exercises', '')
        exercises = [e for e in exercises.split(',') if e]
        if not exercises:
            exercises = [e.name for e in Exercise.all()]

        for exercise in exercises:
            logging.info("Creating task chain for %s", exercise)
            enqueue_task(exercise, start_dt, end_dt, None, uid, 0)

def enqueue_task(exid, start_dt, end_dt, cursor, uid, i):
    # see http://blog.notdot.net/2010/03/Task-Queue-task-chaining-done-right
    try:
        key_name = ExerciseStatisticShard.make_key(exid, start_dt, end_dt, cursor)
        task_name = '_'.join(map(str, [key_name, uid, i]))
        task_name = re.sub(r'[^a-zA-Z0-9_-]{1}', '_', task_name)

        deferred.defer( fancy_stats_deferred, exid, start_dt, end_dt,
                        cursor, uid, i,
                        _name = task_name,
                        _queue = 'fancy-exercise-stats-queue')

    except (taskqueue.TaskAlreadyExistsError, taskqueue.TombstonedTaskError):
        logging.info("Ignoring task named '%s' as it already exists", task_name)

def fancy_stats_deferred(exid, start_dt, end_dt, cursor, uid, i):
    key_name = ExerciseStatisticShard.make_key(exid, start_dt, end_dt, cursor)
    if cursor and ExerciseStatisticShard.get_by_key_name(key_name):
        # We've already run, die.
        return

    query = ProblemLog.all()
    query.filter('exercise =', exid)
    query.filter('correct =', True)
    query.filter('time_done >=', start_dt)
    query.filter('time_done <', end_dt)
    query.order('-time_done')

    if cursor:
        query.with_cursor(cursor)

    problem_logs = query.fetch(1000)
    if len(problem_logs) > 0:
        logging.info("processing %d logs for %s" % (len(problem_logs), exid))

        stats = fancy_stats_from_logs(problem_logs)
        pickled = pickle.dumps(stats, 2)

        shard = ExerciseStatisticShard(
            key_name = key_name,
            exid = exid,
            start_dt = start_dt,
            end_dt = end_dt,
            cursor = cursor,
            blob_val = pickled)
        shard.put()

        enqueue_task(exid, start_dt, end_dt, query.cursor(), uid, i+1)
    else:
        # No more problem logs left to process
        logging.info("Summing all stats for %s", exid)

        all_stats = fancy_stats_shard_reducer(exid, start_dt, end_dt)

        model = ExerciseStatistic(
            key_name = ExerciseStatistic.make_key(exid, start_dt, end_dt),
            exid = exid,
            start_dt = start_dt,
            end_dt = end_dt,
            blob_val = pickle.dumps(all_stats, 2),
            log_count = all_stats['log_count'])
        model.put()

        logging.info("done processing %d logs for %s", all_stats['log_count'], exid)

def fancy_stats_from_logs(problem_logs):
    count = 0
    freq_table = {}
    sugg_freq_table = {}
    prof_freq_table = {}

    for problem_log in problem_logs:
        # cast longs to ints when possible
        time = int(problem_log.time_taken)

        count += 1
        freq_table[time] = 1 + freq_table.get(time, 0)

        if problem_log.suggested:
            sugg_freq_table[time] = 1 + sugg_freq_table.get(time, 0)

        if problem_log.earned_proficiency:
            problem_num = int(problem_log.problem_number)
            prof_freq_table[problem_num] = 1 + prof_freq_table.get(problem_num, 0)

    return {
        'log_count': count,
        'time_taken_frequencies': freq_table,
        'suggested_time_taken_frequencies': sugg_freq_table,
        'proficiency_problem_number_frequencies': prof_freq_table
    }

def fancy_stats_shard_reducer(exid, start_dt, end_dt):
    query = ExerciseStatisticShard.all()
    query.filter('exid =', exid)
    query.filter('start_dt =', start_dt)
    query.filter('end_dt =', end_dt)

    # log_count can't be just a normal variable because Python closures are confusing
    # http://stackoverflow.com/questions/4851463
    results = {
        'log_count': 0,
        'time_taken_frequencies': {},
        'suggested_time_taken_frequencies': {},
        'proficiency_problem_number_frequencies': {},
    }

    # like dict.update, but it adds instead of replacing
    def dict_update_sum(accumulated, updates):
        for key in updates:
            so_far = accumulated.get(key, 0)
            accumulated[key] = so_far + updates[key]

    def accumulate_from_stat_shard(stat_shard):
        shard_val = pickle.loads(stat_shard.blob_val)

        for dict_name in ['time_taken_frequencies', 'suggested_time_taken_frequencies', 'proficiency_problem_number_frequencies']:
            dict_update_sum(results[dict_name], shard_val[dict_name])

        results['log_count'] += shard_val['log_count']

    while True:
        stat_shards = query.fetch(1000)

        if len(stat_shards) <= 0:
            break

        for stat_shard in stat_shards:
            accumulate_from_stat_shard(stat_shard)

        # Don't need the stat shards any more; get rid of them!
        db.delete(stat_shards)

        query.with_cursor(query.cursor())

    return results
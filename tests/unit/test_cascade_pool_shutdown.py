from scripts.run_hackathon_1000_cascade import _shutdown_process_pool


def test_worker_handles_survive_executor_shutdown():
    class Worker:
        terminated = False

        def is_alive(self):
            return True

        def terminate(self):
            self.terminated = True

    class Pool:
        def __init__(self, worker):
            self._processes = {1: worker}

        def shutdown(self, **kwargs):
            self._processes = None

    worker = Worker()
    _shutdown_process_pool(Pool(worker))
    assert worker.terminated

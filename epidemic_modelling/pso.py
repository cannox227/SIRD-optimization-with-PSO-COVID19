import os
import random
from random import Random

import click
import inspyred
import inspyred.ec.terminators
import numpy as np
import pandas as pd
from inspyred import ec
from inspyred.benchmarks import Benchmark
from inspyred.swarm import topologies
from tqdm import tqdm

from epidemic_modelling.sird_base_model import SIRD


class Config:
    SEED = 42
    MAX_GENERATIONS = 1e2
    POPULATION_SIZE = 1e2
    REPETITIONS = 1
    LAG = 10
    DAYS = 70
    PARAMS_THRESHOLD = 0.99
    FACTOR_LOWER_BOUND = 0.001
    FACTOR_UPPER_BOUND = 1.0
    NAME = "baseline"


class MySIRD(Benchmark):

    def __init__(self, dimensions=3):
        Benchmark.__init__(self, dimensions)
        self.bounder = ec.Bounder(
            [Config.FACTOR_LOWER_BOUND] * self.dimensions,
            Config.FACTOR_UPPER_BOUND * self.dimensions,
        )
        self.maximize = False
        # self.global_optimum = [0 for _ in range(self.dimensions)]
        # self.t = 0
        # Absolute path of the data file
        script_dir = os.path.dirname(os.path.abspath(__file__))
        filepath = os.path.join(script_dir, "../data/daily_processed.csv")
        self.data = pd.read_csv(filepath)
        self.population = 60_000_000
        self.epoch = 0
        random.seed = Config.SEED

    def generator(self, random, args):
        # Generate an initial random candidate for each dimension
        x = [
            random.uniform(Config.FACTOR_LOWER_BOUND, Config.FACTOR_UPPER_BOUND)
            for _ in range(self.dimensions)
        ]
        return x

    # def get_ird(self):
    #     infected = self.data["totale_positivi"].values[:]

    # def write_parameters(self, beta, gamma, delta, fitness):
    #     script_dir = os.path.dirname(os.path.abspath(__file__))
    #     plot_filepath = os.path.join(script_dir, "../data/param.csv")
    #     with open(plot_filepath, "a") as f:
    #         if f.tell() == 0:
    #             f.write("beta,gamma,delta,fitness_value\n")
    #         f.write(f"{beta},{gamma},{delta},{fitness}\n")

    def setup(self):
        # For the moment we are going to consider only the first 10 weeks
        self.initial_conds, _ = self.get_sird_from_data(
            Config.LAG, Config.DAYS + Config.LAG, self.population
        )
        _, self.future_conds = self.get_sird_from_data(
            Config.LAG + 1, Config.DAYS + Config.LAG + 1, self.population
        )

    def evaluator(self, candidates, args):
        fitness = []

        future_params = [
            self.future_conds["initial_S"],
            self.future_conds["initial_I"],
            self.future_conds["initial_R"],
            self.future_conds["initial_D"],
        ]

        for idx, (beta, gamma, delta) in tqdm(enumerate(candidates)):
            model = SIRD(beta=beta, gamma=gamma, delta=delta)
            # solve
            days = Config.DAYS
            # pickup GT
            model.solve(self.initial_conds, days)
            # Values obtained
            computed_S, computed_I, computed_R, computed_D, sum_params = (
                model.get_sird_values().values()
            )
            current_params = [computed_S, computed_I, computed_R, computed_D]
            # Check if the sum of the parameters is valid
            assert (
                sum_params >= Config.PARAMS_THRESHOLD
            ), f"Sum of parameters is less than {Config.PARAMS_THRESHOLD}"

            # compute loss
            losses = model.compute_loss(current_params, future_params, loss="MSE")

            # Print losses obtained
            # print(
            #     f"Losses: S: {loss_susceptible}, I: {loss_infected}, R: {loss_recovered}, D: {loss_deceased}"
            # )

            loss_normalized = np.mean(losses)
            # print(f"Loss normalized: {loss_normalized}")

            fitness.append(loss_normalized)
            # print(f"\nFitness: {loss_normalized}\n")
        self.epoch += 1
        return fitness

    def should_terminate(self, population, num_generations, num_evaluations, args):
        print(f"Generation # {num_generations} ...")
        return num_generations >= Config.MAX_GENERATIONS

    def get_sird_from_data(self, start_week: int, end_week: int, population: int):
        infected_t = (
            self.data["totale_positivi"]
            .iloc[start_week:end_week]
            .to_numpy()
            .astype(float)
        )
        recovered_t = (
            self.data["dimessi_guariti"]
            .iloc[start_week:end_week]
            .to_numpy()
            .astype(float)
        )
        deceased_t = (
            self.data["deceduti"].iloc[start_week:end_week].to_numpy().astype(float)
        )
        susceptible_t = (
            self.data["suscettibili"].iloc[start_week:end_week].to_numpy().astype(float)
        )
        all_conds = {
            "population": population,
            "initial_I": infected_t,
            "initial_R": recovered_t,
            "initial_D": deceased_t,
            "initial_S": susceptible_t,
        }
        initial_conds = {
            "population": population,
            "initial_I": infected_t[0],
            "initial_R": recovered_t[0],
            "initial_D": deceased_t[0],
            "initial_S": susceptible_t[0],
        }
        return initial_conds, all_conds

    def save_best_solution(self, final_pop, display=True):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        best_solution_filepath = os.path.join(
            script_dir, f"../data/solutions/{Config.NAME}.csv"
        )

        best = min(final_pop, key=lambda x: x.fitness)

        with open(best_solution_filepath, "a+") as f:
            if f.tell() == 0:
                f.write("beta,gamma,delta,fittness\n")
            f.write(
                f"{best.candidate[0]},{best.candidate[1]},{best.candidate[2]},{best.fitness}\n"
            )

        if display:
            print(f"Best solution: {best.candidate} with fitness: {best.fitness}")


def clean_paths():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    best_solution_filepath = os.path.join(
        script_dir, f"../data/solutions/{Config.NAME}.csv"
    )
    if os.path.exists(best_solution_filepath):
        os.remove(best_solution_filepath)


@click.command()
@click.option("--display", default=True, is_flag=True, help="Display the best solution")
@click.option("--baseline", default=True, is_flag=True, help="Run the baseline")
@click.option(
    "--shorter-weeks",
    default=False,
    is_flag=True,
    help="Run the baseline with shorter weeks",
)
@click.option("--prng", default=None, help="Seed for the pseudorandom number generator")
def main(display, baseline, shorter_weeks, prng):
    if shorter_weeks:
        Config.DAYS = 7
        Config.REPETITIONS = 10
        Config.NAME = "shorter_weeks"

    clean_paths()

    for _ in range(Config.REPETITIONS):
        problem = MySIRD(3)
        problem.setup()

        # Initialization of pseudorandom number generator
        if prng is None:
            prng = Random()
            prng.seed(Config.SEED)

        # Defining the 3 parameters to optimize
        ea = inspyred.swarm.PSO(prng)
        ea.terminator = problem.should_terminate
        ea.topology = topologies.ring_topology

        final_pop = ea.evolve(
            generator=problem.generator,
            evaluator=problem.evaluator,
            pop_size=Config.POPULATION_SIZE,
            bounder=problem.bounder,
            maximize=problem.maximize,
        )

        problem.save_best_solution(final_pop, display)

        Config.LAG += Config.DAYS

    # # Write on csv the best solution
    # best_solution_filepath = os.path.join(script_dir, "../data/best_solution.csv")
    # with open(best_solution_filepath, "w") as f:
    #     f.write("beta,gamma,delta\n")
    #     f.write(f"{best.candidate[0]},{best.candidate[1]},{best.candidate[2]}\n")
    #
    # return ea


if __name__ == "__main__":
    main(display=True)

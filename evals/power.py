"""What difference is this eval set big enough to detect?

Carried in from the 07-30 finding on the previous project. Comparing two systems
question by question, the ties cancel under a sign flip, so only the questions where the
two disagree carry any information. With k disagreements the smallest two sided p value a
permutation test can return is 2 / 2**k.

An eval set that cannot reach p < 0.05 at any effect size produces arguments, not
answers. Check the floor before running the comparison, not after reading it.
"""


def p_floor(k):
    """Smallest two sided p value reachable when k questions differ."""
    if k <= 0:
        return 1.0
    return min(1.0, 2.0 / (2 ** k))


def min_differing(alpha=0.05, cap=64):
    """Fewest differing questions needed before p < alpha is even possible."""
    for k in range(1, cap + 1):
        if p_floor(k) < alpha:
            return k
    return None


def describe(n_questions, n_by_answer, alpha=0.05):
    """n_questions is every question. n_by_answer is the subset with a gold answer.

    Both counts matter and they are easy to conflate. A system comparison scores all 30,
    because a refusal is right or wrong the same way an answer is. Only the 22 with a
    gold query are scored by comparing result sets.
    """
    k = min_differing(alpha)
    return (
        "%d questions, each one right or wrong, of which %d are scored against a gold answer\n"
        "a comparison needs at least %d of them to disagree before p < %.2f is reachable\n"
        "that is %.1f percent of the set, and a smaller real effect is undetectable here"
        % (n_questions, n_by_answer, k, alpha, 100.0 * k / n_questions)
    )

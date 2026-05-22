# xs_regression_zoo — auto-generated ridge XS alphas

Each alpha module subclasses XsRegressionBase, fits a per-day
ridge regression of next-bar return on a small feature vector
(momentum / vol / mean-reversion / volume), and emits an
equal-weight long-short basket on the predicted scores.

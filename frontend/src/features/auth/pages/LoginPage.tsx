import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useLogin } from "../hooks";
import { useAuthStore } from "../../../stores/authStore";
import { Button } from "../../../components/Button";

export const LoginPage = () => {
  const navigate = useNavigate();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const loginMutation = useLogin();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  if (isAuthenticated) {
    return <Navigate to="/review" replace />;
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    loginMutation.mutate(
      { username, password },
      {
        onSuccess: () => {
          navigate("/review", { replace: true });
        },
      },
    );
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-100 px-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded border border-slate-200 bg-white p-6 shadow-sm"
      >
        <h1 className="text-xl font-semibold text-slate-950">Lebanon News</h1>
        <div className="mt-6 space-y-4">
          <label className="block text-sm font-medium text-slate-700">
            Username
            <input
              className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-slate-950"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              required
            />
          </label>
          <label className="block text-sm font-medium text-slate-700">
            Password
            <input
              className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-slate-950"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
        </div>
        {loginMutation.isError ? (
          <p className="mt-4 text-sm text-red-600">Login failed.</p>
        ) : null}
        <Button className="mt-6 w-full" type="submit" disabled={loginMutation.isPending}>
          {loginMutation.isPending ? "Signing in" : "Sign in"}
        </Button>
      </form>
    </main>
  );
};

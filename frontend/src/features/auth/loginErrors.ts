import axios from "axios";

export const getLoginErrorMessage = (error: unknown): string => {
  if (axios.isAxiosError(error)) {
    if (!error.response) {
      return "Could not sign in right now. If you were already signed in on this browser, open the app home page instead.";
    }

    const detail = error.response.data?.detail;
    if (typeof detail === "string" && detail.trim() !== "") {
      return detail;
    }

    if (error.response.status === 429) {
      return "Too many failed login attempts. Try again later.";
    }

    if (error.response.status === 401) {
      return "Incorrect username or password. Please check the credentials and try again.";
    }
  }

  return "Sign-in failed. Please try again.";
};

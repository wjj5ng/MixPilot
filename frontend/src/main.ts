import { mount } from "svelte";
import App from "./App.svelte";
import "./app.css";

const root = document.getElementById("app");
if (!root) {
  throw new Error("missing #app root element");
}

mount(App, { target: root });

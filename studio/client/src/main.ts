import {mount} from 'svelte'
import App from './App.svelte'
import './theme.css'
try{document.documentElement.dataset.theme=localStorage.getItem('studio.theme')==='light'?'light':'dark'}catch{document.documentElement.dataset.theme='dark'}
mount(App,{target:document.querySelector('#app')!})

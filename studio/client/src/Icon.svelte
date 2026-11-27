<script lang="ts">
 let {name,size=20}:{name:string,size?:number}=$props()
 const icons:Record<string,string>={
 windows:'M3 4h8v7H3z M13 4h8v7h-8z M3 13h8v7H3z M13 13h8v7h-8z',
 macos:'M3 4h18v13H3z M8 21h8 M12 17v4',
 tvos:'M2 5h20v13H2z M7 21h10 M8 2l4 3 4-3',
 ios:'M7 2h10a1 1 0 011 1v18a1 1 0 01-1 1H7a1 1 0 01-1-1V3a1 1 0 011-1z M10 5h4 M11 19h2',
 android:'M6 10h12v8H6z M6 8a6 6 0 0112 0z M8 3 6 1 M16 3l2-2 M3 11v5 M21 11v5 M9 18v4 M15 18v4',
 home:'M3 3h8v8H3z M14 3h7v5h-7z M14 11h7v10h-7z M3 14h8v7H3z',
 networks:'M4 6h6l4 12h6 M4 18h6l4-12h6 M17 3l3 3-3 3 M17 15l3 3-3 3',
 library:'M3 4h4v16H3z M9 4h4v16H9z M15 5l4-1 3 15-4 1z',
 devices:'M2 4h13v11H2z M5 18h7 M17 9h5v12h-5z',
 release:'M12 3v12 M7 8l5-5 5 5 M4 14v6h16v-6',
 spark:'M12 3l2.1 6.9L21 12l-6.9 2.1L12 21l-2.1-6.9L3 12l6.9-2.1z',
 arrow:'M5 12h14 M14 7l5 5-5 5'}
</script>
<svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d={icons[name]||icons.home}/></svg>

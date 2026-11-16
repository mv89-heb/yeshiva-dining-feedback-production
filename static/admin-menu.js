(function(){
  const byId=id=>document.getElementById(id);
  const sequence={weekly:0,daily:0};
  const labels={
    he:{loading:"טוען את התפריט הקיים…",weekly:"התפריט הקיים נטען. אפשר לערוך ולשמור.",inherited:"לא הוגדר חריג לתאריך זה; מוצג התפריט השבועי.",override:"נטען חריג ייעודי לתאריך זה.",error:"לא ניתן לטעון את הבחירות הקיימות. נסו לרענן את העמוד."},
    en:{loading:"Loading the saved menu…",weekly:"Saved menu loaded. You can edit and save it.",inherited:"No date override exists; the weekly menu is shown.",override:"A date-specific override is loaded.",error:"Could not load the saved selections. Refresh the page and try again."}
  };
  const lang=document.documentElement.lang==='he'?'he':'en';
  async function sync(scope){
    const weekday=byId('weekly-weekday')?.value;
    const meal=byId(scope==='weekly'?'weekly-meal':'daily-meal')?.value;
    const date=byId('daily-date')?.value;
    const status=byId(scope+'-menu-status');
    const form=byId(scope+'-menu-form');
    const submit=form?.querySelector('button[type="submit"]');
    if(!meal||(scope==='daily'&&!date))return;
    const current=++sequence[scope];
    if(submit)submit.disabled=true;
    if(status)status.textContent=labels[lang].loading;
    const params=new URLSearchParams({scope,meal_type:meal});
    if(scope==='weekly')params.set('weekday',weekday);else params.set('date',date);
    try{
      const response=await fetch('/api/admin/menu?'+params.toString(),{headers:{Accept:'application/json'},cache:'no-store'});
      if(!response.ok)throw new Error('menu request failed');
      const data=await response.json();
      if(current!==sequence[scope])return;
      const prefix=scope==='weekly'?'weekly':'daily';
      document.querySelectorAll('[id^="'+prefix+'-"]').forEach(element=>{if(element.type==='checkbox')element.checked=false;});
      (data.dishes||[]).forEach(item=>{
        const checkbox=byId(prefix+'-'+item.slug);
        const category=byId(prefix+'-category-'+item.slug);
        if(checkbox)checkbox.checked=true;
        if(category)category.value=item.category;
      });
      if(status)status.textContent=scope==='weekly'?labels[lang].weekly:(data.override?labels[lang].override:labels[lang].inherited);
      if(submit)submit.disabled=false;
    }catch(error){if(current===sequence[scope]&&status)status.textContent=labels[lang].error;}
  }
  ['weekly-weekday','weekly-meal'].forEach(id=>byId(id)?.addEventListener('change',()=>sync('weekly')));
  ['daily-date','daily-meal'].forEach(id=>byId(id)?.addEventListener('change',()=>sync('daily')));
  sync('weekly');sync('daily');
})();